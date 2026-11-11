import uuid
from collections import defaultdict
from datetime import datetime, time

from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, NotFound, ValidationError
from rest_framework.response import Response

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
from .serializers import (
    AddMemberSerializer,
    AuditLogSerializer,
    CommentSerializer,
    DocumentSerializer,
    DocumentVersionSerializer,
    TagSerializer,
    UserSerializer,
    WorkspaceMemberSerializer,
    WorkspaceSerializer,
)


class Conflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = 'A record with these values already exists.'
    default_code = 'conflict'


def parse_uuid(name, value):
    try:
        return uuid.UUID(str(value))
    except ValueError:
        raise ValidationError({name: 'Not a valid UUID.'})


def parse_when(name, value, end_of_day=False):
    moment = parse_datetime(value)
    if moment is None:
        day = parse_date(value)
        if day is None:
            raise ValidationError({name: 'Use an ISO date (2026-11-11) or datetime.'})
        moment = datetime.combine(day, time.max if end_of_day else time.min)
    if timezone.is_naive(moment):
        moment = timezone.make_aware(moment)
    return moment


def save_version(document, user):
    DocumentVersion.objects.create(
        document=document,
        content=document.content,
        version_number=document.versions.count() + 1,
        saved_by=user,
    )


class ConflictOnDuplicateMixin:
    def perform_create(self, serializer):
        try:
            with transaction.atomic():
                serializer.save()
        except IntegrityError:
            raise Conflict()

    def perform_update(self, serializer):
        try:
            with transaction.atomic():
                serializer.save()
        except IntegrityError:
            raise Conflict()


class UserViewSet(ConflictOnDuplicateMixin, viewsets.ModelViewSet):
    queryset = User.objects.order_by('created_at')
    serializer_class = UserSerializer


class WorkspaceViewSet(viewsets.ModelViewSet):
    serializer_class = WorkspaceSerializer

    def get_queryset(self):
        return (
            Workspace.objects.select_related('owner')
            .annotate(member_count=Count('members', distinct=True))
            .order_by('created_at')
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            workspace = serializer.save()
            WorkspaceMember.objects.create(
                workspace=workspace, user=workspace.owner, role=WorkspaceMember.Role.ADMIN
            )
            AuditLog.objects.create(
                actor=workspace.owner,
                action='created',
                model_name='Workspace',
                object_id=str(workspace.id),
            )
        workspace = self.get_queryset().get(pk=workspace.pk)
        return Response(self.get_serializer(workspace).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get', 'post'], url_path='members')
    def members(self, request, pk=None):
        workspace = self.get_object()

        if request.method == 'GET':
            members = workspace.members.select_related('user').order_by('joined_at')
            return Response(WorkspaceMemberSerializer(members, many=True).data)

        if not workspace.is_active:
            raise ValidationError({'workspace': 'Members cannot be added to an inactive workspace.'})
        serializer = AddMemberSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user = User.objects.get(pk=serializer.validated_data['user'])
        except User.DoesNotExist:
            raise NotFound('User not found.')
        try:
            with transaction.atomic():
                member = WorkspaceMember.objects.create(
                    workspace=workspace, user=user, role=serializer.validated_data['role']
                )
        except IntegrityError:
            raise Conflict('This user is already a member of the workspace.')
        return Response(WorkspaceMemberSerializer(member).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'], url_path='summary')
    def summary(self, request, pk=None):
        workspace = self.get_object()
        document_ids = workspace.documents.values_list('id', flat=True)
        return Response({
            'workspace': workspace.id,
            'document_count': workspace.documents.aggregate(n=Count('id'))['n'],
            'member_count': workspace.members.aggregate(n=Count('id'))['n'],
            'comment_count': Comment.objects.filter(document_id__in=document_ids).aggregate(
                n=Count('id')
            )['n'],
        })


class DocumentViewSet(viewsets.ModelViewSet):
    serializer_class = DocumentSerializer

    def get_queryset(self):
        queryset = (
            Document.objects.select_related('workspace', 'created_by')
            .prefetch_related('tags')
            .order_by('-updated_at')
        )
        if self.action != 'list':
            return queryset

        params = self.request.query_params
        if params.get('workspace'):
            queryset = queryset.filter(workspace_id=parse_uuid('workspace', params['workspace']))
        if params.get('status'):
            wanted = [s.strip() for s in params['status'].split(',')]
            unknown = [s for s in wanted if s not in Document.Status.values]
            if unknown:
                raise ValidationError({'status': f'Unknown status: {", ".join(unknown)}.'})
            queryset = queryset.filter(status__in=wanted)
        if params.get('tag'):
            queryset = queryset.filter(tags__name__iexact=params['tag'])
        if params.get('search'):
            term = params['search']
            queryset = queryset.filter(Q(title__icontains=term) | Q(content__icontains=term))
        return queryset.distinct()

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            document = serializer.save()
            save_version(document, document.created_by)
        document = self.get_queryset().get(pk=document.pk)
        return Response(self.get_serializer(document).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        document = self.get_object()
        serializer = self.get_serializer(document, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        saved_by = serializer.validated_data.get('updated_by') or document.created_by
        with transaction.atomic():
            document = serializer.save()
            save_version(document, saved_by)
        document = self.get_queryset().get(pk=document.pk)
        return Response(self.get_serializer(document).data)

    @action(detail=True, methods=['get'], url_path='versions')
    def versions(self, request, pk=None):
        document = self.get_object()
        versions = (
            DocumentVersion.objects.filter(document=document)
            .select_related('saved_by')
            .order_by('version_number')
        )
        return Response(DocumentVersionSerializer(versions, many=True).data)

    @action(detail=True, methods=['get'], url_path='stats')
    def stats(self, request, pk=None):
        document = self.get_object()
        counts = Document.objects.filter(pk=document.pk).aggregate(
            version_count=Count('versions', distinct=True),
            comment_count=Count('comments', distinct=True),
            contributor_count=Count('versions__saved_by', distinct=True),
        )
        return Response({'document': document.id, **counts})

    @action(detail=True, methods=['post'], url_path='tags')
    def tags(self, request, pk=None):
        document = self.get_object()
        names = request.data.get('tags')
        valid = (
            isinstance(names, list)
            and names
            and all(isinstance(n, str) and 0 < len(n.strip()) <= 100 for n in names)
        )
        if not valid:
            raise ValidationError(
                {'tags': 'Send a non-empty list of tag names, each up to 100 characters.'}
            )
        with transaction.atomic():
            tags = [Tag.objects.get_or_create(name=n.strip())[0] for n in names]
            document.tags.add(*tags)
        return Response({
            'document': document.id,
            'tags': sorted(tag.name for tag in document.tags.all()),
        })


class CommentViewSet(viewsets.ModelViewSet):
    queryset = Comment.objects.select_related('author', 'document', 'parent')
    serializer_class = CommentSerializer

    def list(self, request, *args, **kwargs):
        raw = request.query_params.get('document')
        if not raw:
            raise ValidationError({'document': 'Pass ?document=<id> to list comments.'})
        document_id = parse_uuid('document', raw)
        if not Document.objects.filter(pk=document_id).exists():
            raise NotFound('Document not found.')

        comments = (
            Comment.objects.filter(document_id=document_id)
            .select_related('author')
            .order_by('created_at')
        )
        children = defaultdict(list)
        for comment in comments:
            children[comment.parent_id].append(comment)

        context = {**self.get_serializer_context(), 'children': children}
        serializer = self.get_serializer(children[None], many=True, context=context)
        return Response(serializer.data)


class TagViewSet(ConflictOnDuplicateMixin, viewsets.ModelViewSet):
    queryset = Tag.objects.order_by('name')
    serializer_class = TagSerializer


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AuditLogSerializer

    def get_queryset(self):
        queryset = AuditLog.objects.select_related('actor')
        if self.action != 'list':
            return queryset

        params = self.request.query_params
        if params.get('actor'):
            queryset = queryset.filter(actor_id=parse_uuid('actor', params['actor']))
        if params.get('from'):
            queryset = queryset.filter(timestamp__gte=parse_when('from', params['from']))
        if params.get('to'):
            queryset = queryset.filter(
                timestamp__lte=parse_when('to', params['to'], end_of_day=True)
            )
        return queryset
