"""
Email sender module for Yet Another Flask Survival Kit (YAFSK).

Author:
    Johnny De Castro <j@jdcastro.co>

Copyright:
    (c) 2024 - 2025 Johnny De Castro. All rights reserved.

License:
    Apache License 2.0 - http://www.apache.org/licenses/LICENSE-2.0

"""

# Python standard library imports
import threading
from typing import List, Optional, Tuple, Union

from flask import current_app

# Third party imports
from flask_mail import Mail, Message
from werkzeug.datastructures import FileStorage

# Local application imports
from app.config import Config

mail = Mail()


class EmailSender:
    def __init__(
        self,
        subject: str,
        message: str,
        recipients: Optional[Union[str, List[str]]] = None,
        attachments: Optional[List[Union[FileStorage, Tuple[str, str]]]] = None,
    ):
        self.subject = subject
        self.message = message
        self.sender = Config.MAIL_DEFAULT_SENDER
        self.recipients = self._get_recipients(recipients)
        self.attachments = attachments or []

    @staticmethod
    def _get_recipients(recipients: Optional[Union[str, List[str]]]) -> List[str]:
        default_recipient = Config.CONTACT_EMAIL
        if recipients is None:
            return [default_recipient]
        if isinstance(recipients, str):
            return [default_recipient, recipients]
        if isinstance(recipients, list):
            return [default_recipient] + recipients
        raise ValueError("Recipients must be a string or a list of strings")

    @staticmethod
    def send_async_email(app, msg: Message) -> None:
        try:
            with app.app_context():
                mail.send(msg)
        except Exception as e:
            current_app.logger.error(f"Failed to send email: {e}")

    def send_mail(self) -> threading.Thread:
        msg = Message(
            subject=self.subject,
            sender=self.sender,
            recipients=self.recipients,
            body=self.message,
        )
        self._attach_files(msg)
        app = current_app._get_current_object()
        thread = threading.Thread(target=self.send_async_email, args=(app, msg))
        thread.start()
        return thread

    def _attach_files(self, msg: Message) -> None:
        for attachment in self.attachments:
            if isinstance(attachment, FileStorage):
                msg.attach(
                    filename=attachment.filename,
                    content_type=attachment.content_type,
                    data=attachment.read(),
                )
            elif isinstance(attachment, tuple):
                filename, file_path = attachment
                with open(file_path, "rb") as f:
                    msg.attach(
                        filename=filename,
                        content_type="application/octet-stream",
                        data=f.read(),
                    )


def send_email(
    subject: str,
    message: str,
    recipients: Optional[Union[str, List[str]]] = None,
    attachments: Optional[List[Union[FileStorage, Tuple[str, str]]]] = None,
) -> threading.Thread:
    email_sender = EmailSender(subject, message, recipients, attachments)
    return email_sender.send_mail()
