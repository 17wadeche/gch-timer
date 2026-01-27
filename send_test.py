import os
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
api_key = os.getenv("SENDGRID_API_KEY")
if not api_key:
    raise SystemExit("SENDGRID_API_KEY not set")
message = Mail(
    from_email="chey.wade@medtronic.com",
    to_emails="chey.wade@medtronic.com",
    subject="SendGrid test",
    html_content="It worked!"
)
sg = SendGridAPIClient(api_key)
resp = sg.send(message)
print(resp.status_code)
print(resp.body)
print(resp.headers)