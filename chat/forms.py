from django import forms
from django.contrib.auth import get_user_model

from .inbox import reachable_users
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
                    "placeholder": "Write a message…",
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


class NewConversationForm(forms.Form):
    """One to fifteen reachable people, plus an optional group name."""

    title = forms.CharField(max_length=80, required=False, label="Group name")

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        data = self.data
        raw_values = data.getlist("to") if hasattr(data, "getlist") else []
        pks = []
        seen = set()
        for raw in raw_values:
            try:
                pk = int(raw)
            except (TypeError, ValueError):
                raise forms.ValidationError("You can't message this person.")
            if pk == self.user.pk or pk in seen:
                continue
            seen.add(pk)
            pks.append(pk)
        reachable = set(reachable_users(self.user).values_list("pk", flat=True))
        if any(pk not in reachable for pk in pks):
            raise forms.ValidationError("You can't message this person.")
        if not pks or len(pks) > 15:
            raise forms.ValidationError("Choose between 1 and 15 people.")
        User = get_user_model()
        users = list(User.objects.filter(pk__in=pks))
        by_pk = {user.pk: user for user in users}
        cleaned["people"] = [by_pk[pk] for pk in pks]
        return cleaned
