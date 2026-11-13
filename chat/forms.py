from django import forms

from .models import Message


class MessageForm(forms.ModelForm):
    class Meta:
        model = Message
        fields = ["body"]
        widgets = {
            "body": forms.Textarea(
                attrs={
                    "rows": 2,
                    "maxlength": Message.MAX_BODY_LENGTH,
                    "placeholder": "Message your team…",
                }
            ),
        }
        labels = {"body": "New message"}
        help_texts = {
            "body": f"Up to {Message.MAX_BODY_LENGTH} characters.",
        }

    def clean_body(self):
        body = (self.cleaned_data.get("body") or "").strip()
        if not body:
            raise forms.ValidationError("Write a message before sending.")
        return body
