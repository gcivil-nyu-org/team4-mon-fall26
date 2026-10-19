from django.contrib.auth.tokens import PasswordResetTokenGenerator


class EmailVerificationTokenGenerator(PasswordResetTokenGenerator):
    """Signed, expiring token for the link in the confirmation email.

    It reuses Django's password-reset machinery, so tampered tokens fail and old
    ones expire after settings.PASSWORD_RESET_TIMEOUT (3 days by default).

    - A different key_salt means a password-reset token can never be used here.
    - is_active and last_login are part of the hash, so a link works once: after
      the account is activated (or the user has logged in) the same link is dead.
    - The email address is part of the hash, so changing it kills older links.
    """

    key_salt = "accounts.tokens.EmailVerificationTokenGenerator"

    def _make_hash_value(self, user, timestamp):
        last_login = "" if user.last_login is None else user.last_login.replace(microsecond=0, tzinfo=None)
        return f"{user.pk}{user.email}{user.is_active}{last_login}{timestamp}"


email_verification_token = EmailVerificationTokenGenerator()
