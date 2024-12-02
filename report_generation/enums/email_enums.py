from enum import Enum


class EmailRecipientType(Enum):
    ACCOUNT = "account"
    INTERNAL = "internal"


class DefaultEmailTypes(Enum):
    # Format: (recipient_type, department/None, default_recipients)
    ACCOUNT_NOTIFICATION = (EmailRecipientType.ACCOUNT, None, [])
    INTERNAL_GENERAL = (
        EmailRecipientType.INTERNAL,
        "general",
        ["christine@sunriselogistics.net"],
    )

    def __init__(
        self,
        recipient_type: EmailRecipientType,
        department: str | None,
        default_recipients: list[str],
    ) -> None:
        self.recipient_type = recipient_type
        self.department = department
        self.default_recipients = default_recipients

    @property
    def is_internal(self) -> bool:
        return self.recipient_type == EmailRecipientType.INTERNAL

    @property
    def is_account(self) -> bool:
        return self.recipient_type == EmailRecipientType.ACCOUNT
