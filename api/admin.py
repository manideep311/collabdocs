from django.contrib import admin

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

for model in (User, Workspace, WorkspaceMember, Document, DocumentVersion, Comment, Tag, AuditLog):
    admin.site.register(model)
