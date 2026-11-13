from django import forms

from teams.models import Sport

from .models import Reply, Topic


def _required_text(value, message):
    value = (value or "").strip()
    if not value:
        raise forms.ValidationError(message)
    return value


class TopicForm(forms.ModelForm):
    sport = forms.ModelChoiceField(
        queryset=Sport.objects.order_by("name"),
        required=False,
        empty_label="General",
        label="Sport",
        help_text="Choose General for a topic about no single sport.",
    )

    class Meta:
        model = Topic
        fields = ["sport", "title", "body"]
        widgets = {
            "title": forms.TextInput(attrs={"maxlength": Topic.MAX_TITLE_LENGTH}),
            "body": forms.Textarea(
                attrs={"rows": 6, "maxlength": Topic.MAX_BODY_LENGTH}
            ),
        }
        labels = {"body": "Post"}
        help_texts = {
            "title": f"Up to {Topic.MAX_TITLE_LENGTH} characters.",
            "body": f"Up to {Topic.MAX_BODY_LENGTH} characters.",
        }

    def clean_title(self):
        return _required_text(self.cleaned_data.get("title"), "Give the topic a title.")

    def clean_body(self):
        return _required_text(
            self.cleaned_data.get("body"), "Write a post before you start the topic."
        )


class ReplyForm(forms.ModelForm):
    class Meta:
        model = Reply
        fields = ["body"]
        widgets = {
            "body": forms.Textarea(
                attrs={
                    "rows": 3,
                    "maxlength": Reply.MAX_BODY_LENGTH,
                    "placeholder": "Reply to this topic…",
                }
            ),
        }
        labels = {"body": "Your reply"}
        help_texts = {"body": f"Up to {Reply.MAX_BODY_LENGTH} characters."}

    def clean_body(self):
        return _required_text(
            self.cleaned_data.get("body"), "Write a reply before posting."
        )
