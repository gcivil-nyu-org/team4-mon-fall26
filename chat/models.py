from django.conf import settings
from django.db import models


class Conversation(models.Model):
    """One chat thread: a team chat, a 1:1 chat, or a group chat.

    Team membership stays derived from ``teams.Roster``. Direct and group
    chats track their people in ``ConversationMember`` instead.
    """

    class Kind(models.TextChoices):
        TEAM = "team", "Team"
        DIRECT = "direct", "Direct message"
        GROUP = "group", "Group"

    kind = models.CharField(max_length=10, choices=Kind.choices)
    team = models.OneToOneField(
        "teams.Team",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="conversation",
    )
    direct_key = models.CharField(max_length=64, null=True, blank=True, unique=True)
    title = models.CharField(max_length=80, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(kind="team", team__isnull=False)
                | (~models.Q(kind="team") & models.Q(team__isnull=True)),
                name="team_kind_requires_team",
            ),
            models.CheckConstraint(
                condition=models.Q(kind="direct", direct_key__isnull=False)
                | (~models.Q(kind="direct") & models.Q(direct_key__isnull=True)),
                name="direct_kind_requires_key",
            ),
        ]

    def __str__(self):
        if self.kind == self.Kind.TEAM:
            return f"Team chat: {self.team}"
        if self.kind == self.Kind.DIRECT:
            return "Direct message"
        return self.title or "Group chat"

    @classmethod
    def for_team(cls, team):
        """The team's chat, creating it on first use."""
        conversation, _ = cls.objects.get_or_create(kind=cls.Kind.TEAM, team=team)
        return conversation

    @staticmethod
    def direct_key_for(user_a, user_b):
        """The shared key for a pair of users, either way round."""
        low, high = sorted((user_a.pk, user_b.pk))
        return f"{low}:{high}"


class ConversationMember(models.Model):
    """One person's seat in a direct or group chat."""

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="memberships"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="conversation_memberships",
    )
    joined_at = models.DateTimeField(auto_now_add=True)
    left_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["conversation", "user"],
                name="unique_member_per_conversation",
            )
        ]

    def __str__(self):
        return f"{self.user} in {self.conversation}"


class ConversationRead(models.Model):
    """When one person last read one conversation."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="conversation_reads",
    )
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="read_markers"
    )
    last_read_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "conversation"],
                name="unique_read_per_user_conversation",
            )
        ]

    def __str__(self):
        return f"{self.user} read {self.conversation} at {self.last_read_at:%Y-%m-%d %H:%M}"


class Block(models.Model):
    """One person blocking another from direct chat."""

    blocker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chat_blocks_made",
    )
    blocked = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chat_blocks_received",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["blocker", "blocked"], name="unique_block_per_pair"
            ),
            models.CheckConstraint(
                condition=~models.Q(blocker=models.F("blocked")),
                name="blocker_differs_from_blocked",
            ),
        ]

    def __str__(self):
        return f"{self.blocker} blocked {self.blocked}"


class Message(models.Model):
    """One chat message in a conversation."""

    MAX_BODY_LENGTH = 500

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chat_messages",
    )
    body = models.CharField(max_length=MAX_BODY_LENGTH)
    created_at = models.DateTimeField(auto_now_add=True)
    is_flagged = models.BooleanField(default=False)

    class Meta:
        ordering = ["created_at", "pk"]

    def __str__(self):
        return f"{self.author}: {self.body[:40]}"
