import "./password-recovery-help.css";

export function PasswordRecoveryHelp({ team = false }) {
  return (
    <details className="password-recovery-help">
      <summary>Forgot password?</summary>
      <div className="password-recovery-help__content">
        <p>
          {team
            ? "Contact the account owner for help resetting your team password."
            : "Continue with email and password to access password recovery on the secure sign-in screen."}
        </p>
      </div>
    </details>
  );
}
