import re

from rest_framework import serializers

from .models import (
    AuditLog,
    Comment,
    Document,
    DocumentVersion,
    Tag,
    User,
    Workspace,
    WorkspaceMember,
)

EMAIL_PATTERN = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


class UserSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'first_name', 'last_name', 'full_name', 'email', 'phone', 'created_at']
        extra_kwargs = {'email': {'validators': []}, 'phone': {'validators': []}}

    def get_full_name(self, obj):
        return f'{obj.first_name} {obj.last_name}'

    def validate_email(self, value):
        value = value.strip().lower()
        if not EMAIL_PATTERN.match(value):
            raise serializers.ValidationError('Enter a valid email address.')
        return value

    def validate_phone(self, value):
        value = value.strip()
        if not re.fullmatch(r'\+?\d{7,14}', value):
            raise serializers.ValidationError('Phone must be 7 to 14 digits, optionally starting with +.')
        return value


class WorkspaceSerializer(serializers.ModelSerializer):
    member_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Workspace
        fields = ['id', 'name', 'owner', 'is_active', 'created_at', 'member_count']

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('Workspace name cannot be blank.')
        return value

    def validate_owner(self, value):
        if self.instance and value != self.instance.owner:
            raise serializers.ValidationError('The owner of a workspace cannot be changed.')
        return value


class WorkspaceMemberSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)

    class Meta:
        model = WorkspaceMember
        fields = ['id', 'user', 'role', 'joined_at']


class AddMemberSerializer(serializers.Serializer):
    user = serializers.UUIDField()
    role = serializers.ChoiceField(
        choices=WorkspaceMember.Role.choices, default=WorkspaceMember.Role.VIEWER
    )


class DocumentSerializer(serializers.ModelSerializer):
    workspace_name = serializers.CharField(source='workspace.name', read_only=True)
    tag_names = serializers.SerializerMethodField()
    updated_by = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), write_only=True, required=False
    )

    class Meta:
        model = Document
        fields = [
            'id', 'title', 'content', 'workspace', 'workspace_name', 'created_by',
            'updated_by', 'status', 'tag_names', 'created_at', 'updated_at',
        ]

    def get_tag_names(self, obj):
        return sorted(tag.name for tag in obj.tags.all())

    def validate_title(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('Title cannot be blank.')
        return value

    def validate(self, attrs):
        if self.instance:
            workspace = self.instance.workspace
            if 'workspace' in attrs and attrs['workspace'] != workspace:
                raise serializers.ValidationError(
                    {'workspace': 'A document cannot be moved to another workspace.'}
                )
            if 'created_by' in attrs and attrs['created_by'] != self.instance.created_by:
                raise serializers.ValidationError(
                    {'created_by': 'The author of a document cannot be changed. Use updated_by.'}
                )
            editor = attrs.get('updated_by') or self.instance.created_by
        else:
            workspace = attrs['workspace']
            editor = attrs.get('created_by')
            if editor is None:
                raise serializers.ValidationError({'created_by': 'This field is required.'})

        if not workspace.is_active:
            raise serializers.ValidationError({'workspace': 'This workspace is inactive.'})

        if editor is not None:
            can_write = WorkspaceMember.objects.filter(
                workspace=workspace,
                user=editor,
                role__in=[WorkspaceMember.Role.ADMIN, WorkspaceMember.Role.EDITOR],
            ).exists()
            if not can_write:
                raise serializers.ValidationError(
                    'Only admins and editors of this workspace can write documents.'
                )
        return attrs

    def create(self, validated_data):
        validated_data.pop('updated_by', None)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data.pop('updated_by', None)
        return super().update(instance, validated_data)


class DocumentVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentVersion
        fields = ['id', 'version_number', 'content', 'saved_by', 'saved_at']


class CommentSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()
    replies = serializers.SerializerMethodField()

    class Meta:
        model = Comment
        fields = ['id', 'document', 'author', 'author_name', 'content', 'parent', 'replies', 'created_at']

    def get_author_name(self, obj):
        if obj.author is None:
            return None
        return f'{obj.author.first_name} {obj.author.last_name}'

    def get_replies(self, obj):
        children = self.context.get('children', {}).get(obj.id, [])
        return CommentSerializer(children, many=True, context=self.context).data

    def validate_content(self, value):
        if not value.strip():
            raise serializers.ValidationError('Comment cannot be blank.')
        return value

    def validate(self, attrs):
        parent = attrs.get('parent')
        document = attrs.get('document') or (self.instance.document if self.instance else None)
        if parent is not None and document is not None and parent.document_id != document.id:
            raise serializers.ValidationError(
                {'parent': 'The parent comment belongs to a different document.'}
            )
        return attrs


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ['id', 'name']
        extra_kwargs = {'name': {'validators': []}}

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('Tag name cannot be blank.')
        return value


class AuditLogSerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()

    class Meta:
        model = AuditLog
        fields = ['id', 'actor', 'actor_name', 'action', 'model_name', 'object_id', 'timestamp']

    def get_actor_name(self, obj):
        if obj.actor is None:
            return None
        return f'{obj.actor.first_name} {obj.actor.last_name}'
