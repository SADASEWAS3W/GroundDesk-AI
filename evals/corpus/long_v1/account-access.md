# Account Access and Authentication Handbook

## Identify the access problem

Account access can involve an email address, a password, and an authenticator code. These are different parts of the login process. Begin by identifying which part is causing difficulty: a forgotten password, a rejected login attempt, or a problem completing two-factor authentication. Describing the failing step makes it easier to choose the relevant instructions without changing unrelated account settings.

First make sure that the email address and password are the ones associated with the account. A password reset message is sent to the account's email address, so entering a different address does not help recover that account. If the browser appears to retain an unsuccessful login state, clear its cache and cookies and try again. When two-factor authentication is enabled, also ensure that the authenticator app is synced.

## Request a password reset

Open the login page and select 'Forgot Password'. Enter the email address associated with the account. The documented delivery time for the password reset email is within 2 minutes. If the message does not arrive, check the spam folder or contact support. Keep the distinction between requesting the message and choosing the new password: requesting an email does not itself complete the password change.

The password reset link expires after 24 hours. This is the validity period of the link, not a waiting period before it can be used. When following the reset flow, choose a new password of at least 12 characters containing a mix of letters, numbers, and symbols. The minimum length and the character mix are both part of the documented requirements; meeting only one does not describe a compliant replacement password.

## Handle unsuccessful login attempts

A forgotten password and an account lock are not the same symptom. If too many failed attempts have locked the account, wait 15 minutes before trying again. This waiting interval belongs to the account-lock troubleshooting instructions and is separate from the reset email delivery time and reset-link expiry. If access still fails after the relevant checks, use the 'Forgot Password' flow or contact support.

For a support request, explain whether the issue occurred before or after the password step and whether an authenticator code was requested. A useful description distinguishes a missing reset email from a code that does not work. Do not include passwords, reset links, current authenticator codes, or backup codes in that description. This is safe handling advice, not an additional authentication method.

## Set up an authenticator

To enable two-factor authentication, open Settings > Account > Security and click 'Enable 2FA'. Scan the displayed QR code using an authenticator app. Examples in the setup guide include Google Authenticator, Authy, and Microsoft Authenticator. The app is used to complete an additional verification step beyond the account password.

After scanning the QR code, enter the 6-digit code from the authenticator app to confirm setup. Once two-factor authentication is enabled, a code from the app is required each time you log in. Scanning and confirming are separate actions: the documented setup includes both the scan and entry of the code. If a login code is not working, the login troubleshooting guide calls for checking that the app is synced.

## Preserve recovery information and understand plan requirements

Backup codes are generated during setup; store them safely in case access to the authenticator app is lost. Treat these codes as recovery information rather than ordinary notes to paste into a support conversation. Keeping them safe is part of preparing for an interruption in access to the authenticator, not a replacement for completing the initial setup.

To disable 2FA, return to the Security settings page, click 'Disable 2FA', and enter a current authenticator code to confirm. Two-factor authentication is mandatory for Enterprise accounts and optional for Free and Pro accounts. Read the disable instructions together with the plan requirement; the existence of a disable action should not be interpreted as permission to bypass an Enterprise requirement.
