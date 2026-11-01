"""Lambda entry points and explicit local adapters for the existing Flask app."""

import base64
from io import BytesIO
import json
import os
import sys
from urllib.parse import unquote

from .delivery import JobProcessor, MemoryMail, MemoryQueue, OutboxDispatcher, SesMail, SqsQueue
from .reminders import AwsScheduler, MemoryScheduler, ReminderService, instant


_application = None


def build_services(settings, store):
    from .calendar import CalendarWorker
    from .oauth import OAuthService

    local = settings.get("AUTOMATION_MODE", "local") == "local"
    clock = settings.get("AUTOMATION_CLOCK")
    epoch_clock = (lambda: instant(clock()).timestamp()) if clock else None
    queue = settings.get("AUTOMATION_QUEUE") or (MemoryQueue() if local else SqsQueue(settings))
    mail = settings.get("AUTOMATION_MAIL") or (MemoryMail() if local else SesMail(settings))
    scheduler = settings.get("AUTOMATION_SCHEDULER") or (MemoryScheduler() if local else AwsScheduler(settings))
    # Google stays disconnected until explicitly connected. Injected Google/secrets
    # adapters let tests exercise OAuth and Calendar entirely offline.
    oauth = settings.get("AUTOMATION_OAUTH") or OAuthService(
        settings, store, google=settings.get("AUTOMATION_GOOGLE"), secrets=settings.get("AUTOMATION_SECRETS"),
        clock=epoch_clock)
    calendar = settings.get("AUTOMATION_CALENDAR_WORKER") or CalendarWorker(
        settings, store, oauth, google=settings.get("AUTOMATION_GOOGLE"), clock=epoch_clock)
    reminders = ReminderService(settings, store, scheduler, clock=settings.get("AUTOMATION_CLOCK"))
    processor = JobProcessor(settings, store, queue, mail, reminders, calendar, clock=settings.get("AUTOMATION_CLOCK"))
    dispatcher = OutboxDispatcher(settings, store, queue, clock=settings.get("AUTOMATION_CLOCK"))
    return {"queue": queue, "mail": mail, "scheduler": scheduler, "google_oauth": oauth,
            "calendar_worker": calendar, "reminders": reminders, "processor": processor, "dispatcher": dispatcher}


def _load_runtime_secret():
    """Fetch existing deployment configuration at cold start, without logging it."""
    name = os.getenv("AUTOMATION_RUNTIME_SECRET_ARN")
    if not name:
        return
    import boto3
    response = boto3.client("secretsmanager").get_secret_value(SecretId=name)
    values = json.loads(response["SecretString"])
    if not isinstance(values, dict) or any(not isinstance(key, str) or not isinstance(value, str)
                                          for key, value in values.items()):
        raise ValueError("Runtime secret must be a JSON map of string environment settings")
    # Deployment environment takes precedence over the imported private configuration.
    for key, value in values.items():
        os.environ.setdefault(key, value)


def application():
    global _application
    if _application is None:
        _load_runtime_secret()
        from .. import create_app
        _application = create_app()
    return _application


def services():
    app = application()
    # One shared factory builds the same adapters for HTTP, dispatcher and worker.
    return app.extensions["automation_services"]


def dispatch_handler(event, context):
    return {"published": services()["dispatcher"].dispatch()}


def queue_handler(event, context):
    return services()["processor"].handle_batch(event)


def dlq_handler(event, context):
    """Acknowledge DLQ diagnostics only after persisting a visible terminal state."""
    app, failures = application(), []
    store = app.extensions["automation_store"]
    for record in event.get("Records", []):
        try:
            payload = json.loads(record["body"])
            if payload.get("kind") == "scheduled_reminder":
                key = services()["reminders"].materialize(payload)
                if key is None:
                    continue
            else:
                key = payload["job_key"]
            with store.transaction() as tx:
                job = tx.get_outbox(key)
                if not job:
                    raise ValueError("Unknown dead-letter job")
                delivery = tx.get_delivery(key) or {"key": key, "attempts": 0}
                if payload.get("delivery_generation", 0) != delivery.get("generation", 0):
                    continue
                if delivery.get("status") not in {"sent", "skipped", "failed"}:
                    delivery.update(status="dead_letter", lease_until=None,
                                    last_error="Queue retries exhausted. Investigate and explicitly replay this job.")
                    tx.save_delivery(delivery)
                tx.audit("automation.job.dead_letter", detail={"job_key": key})
        except Exception:
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}


def api_handler(event, context):
    """API Gateway REST proxy -> WSGI, preserving all Set-Cookie headers."""
    app = application()
    headers = {key.lower(): value for key, value in (event.get("headers") or {}).items()}
    multi = event.get("multiValueHeaders") or {}
    for key, values in multi.items():
        headers[key.lower()] = ("; " if key.lower() == "cookie" else ",").join(values)
    body = event.get("body") or ""
    body = base64.b64decode(body) if event.get("isBase64Encoded") else body.encode("utf-8")
    query = event.get("multiValueQueryStringParameters") or event.get("queryStringParameters") or {}
    from urllib.parse import urlencode
    request_context = event.get("requestContext", {})
    environ = {"REQUEST_METHOD": event.get("httpMethod", "GET"),
               "SCRIPT_NAME": "", "PATH_INFO": unquote(event.get("path", "/")),
               "QUERY_STRING": urlencode(query, doseq=True), "SERVER_NAME": headers.get("host", "localhost"),
               "SERVER_PORT": "443", "SERVER_PROTOCOL": "HTTP/1.1", "wsgi.version": (1, 0),
               "wsgi.url_scheme": "https", "wsgi.input": BytesIO(body), "wsgi.errors": sys.stderr,
               "wsgi.multithread": False, "wsgi.multiprocess": True, "wsgi.run_once": False,
               "CONTENT_LENGTH": str(len(body)),
               "REMOTE_ADDR": request_context.get("identity", {}).get("sourceIp", "127.0.0.1")}
    for key, value in headers.items():
        if key == "content-type":
            environ["CONTENT_TYPE"] = value
        elif key != "content-length":
            environ["HTTP_" + key.upper().replace("-", "_")] = value
    captured = {}

    def start_response(status, response_headers, exc_info=None):
        captured.update(status=int(status.split()[0]), headers=response_headers)

    result = app.wsgi_app(environ, start_response)
    try:
        response_body = b"".join(result)
    finally:
        if hasattr(result, "close"):
            result.close()
    response_headers = {}
    for key, value in captured["headers"]:
        response_headers.setdefault(key, []).append(value)
    return {"statusCode": captured["status"], "multiValueHeaders": response_headers,
            "body": base64.b64encode(response_body).decode("ascii"), "isBase64Encoded": True}


def main():
    from dotenv import load_dotenv
    from pathlib import Path
    load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)
    command = sys.argv[1] if len(sys.argv) > 1 else "dispatch"
    adapters = services()
    if command == "dispatch":
        if isinstance(adapters["queue"], MemoryQueue):
            raise SystemExit("Local queues are process-local; use work-local to dispatch and consume together")
        print(json.dumps({"published": adapters["dispatcher"].dispatch()}))
    elif command == "work-local":
        if not isinstance(adapters["queue"], MemoryQueue):
            raise SystemExit("work-local requires AUTOMATION_MODE=local")
        processed = set()
        for _ in range(20):
            with application().extensions["automation_store"].transaction() as tx:
                jobs = tx.list_outbox()
            jobs = [job for job in jobs if job["key"] not in processed]
            if not jobs:
                break
            for job in jobs:
                processed.add(job["key"])
                try:
                    adapters["processor"].process({"job_key": job["key"],
                                                   "delivery_generation": job.get("replay_generation", 0)})
                except Exception:
                    # Retry state is durable in MySQL; the next local invocation resumes it.
                    pass
        print(json.dumps({"simulated_mail": len(adapters["mail"].messages),
                          "simulated_schedules": len(adapters["scheduler"].schedules)}))
    else:
        raise SystemExit("Usage: python -m app.automation.runtime dispatch|work-local")


if __name__ == "__main__":
    main()
