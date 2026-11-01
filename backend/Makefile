.PHONY: build-ApiFunction build-DispatcherFunction build-WorkerFunction build-DlqFunction

# SAM invokes this in its build container. Only explicit application/certificate
# allowlists enter the artifact; backend/.env and local virtualenvs are excluded.
build-ApiFunction build-DispatcherFunction build-WorkerFunction build-DlqFunction:
	python3 -m pip install --requirement requirements.txt --target "$(ARTIFACTS_DIR)" --no-compile
	python3 scripts/build_automation_lambda.py "$(ARTIFACTS_DIR)"
