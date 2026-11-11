from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from .models import AuditLog, Document


@receiver(pre_save, sender=Document)
def remember_if_new(sender, instance, **kwargs):
    instance._is_new = instance._state.adding


@receiver(post_save, sender=Document)
def log_document_save(sender, instance, **kwargs):
    AuditLog.objects.create(
        actor=instance.created_by,
        action='created' if instance._is_new else 'updated',
        model_name='Document',
        object_id=str(instance.id),
    )
