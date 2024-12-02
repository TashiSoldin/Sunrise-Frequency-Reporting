from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
import smtplib


class OutlookEmailClient:
    def __init__(
        self,
        sender_email: str,
        sender_password: str,
        smtp_server: str = "smtp-mail.outlook.com",
        smtp_port: int = 587,
    ) -> None:
        self.sender_email = sender_email
        self.sender_password = sender_password
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port

    def __enter__(self):
        self.connection = self._create_connection()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.connection.close()

    def _create_connection(self) -> smtplib.SMTP:
        server = smtplib.SMTP(self.smtp_server, self.smtp_port)
        server.starttls()
        server.login(self.sender_email, self.sender_password)
        return server

    def send_email(
        self,
        recipient_email: str,
        subject: str,
        body: str,
        attachments: list[str] | None,
    ) -> None:
        """
        Send a single email with optional attachments.

        Args:
            recipient_email (str): Email address of the recipient
            subject (str): Email subject line
            body (str): Email body content
            attachments (list[str], optional): List of file paths to attach
        """
        msg = MIMEMultipart()
        msg["From"] = self.sender_email
        msg["To"] = recipient_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "html"))

        if attachments:
            for file_path in attachments:
                with open(file_path, "rb") as f:
                    attachment = MIMEApplication(f.read(), _subtype="xlsx")
                    filename = file_path.split("/")[-1]
                    attachment.add_header(
                        "Content-Disposition", "attachment", filename=filename
                    )
                    msg.attach(attachment)

        self.connection.send_message(msg)
