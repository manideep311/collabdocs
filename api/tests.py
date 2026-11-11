from unittest import mock

from django.test import TestCase
from rest_framework.test import APIClient

from .models import AuditLog, Comment, Document, DocumentVersion, Tag, User, Workspace, WorkspaceMember


class ApiTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.samyuktha = self.make_user('Samyuktha', 'samyuktha@example.com', '9000000001')
        self.arjun = self.make_user('Arjun', 'arjun@example.com', '9000000002')

    def make_user(self, first, email, phone):
        return User.objects.create(first_name=first, last_name='Test', email=email, phone=phone)

    def make_workspace(self, owner=None):
        response = self.client.post(
            '/api/workspaces/', {'name': 'Design Squad', 'owner': str(owner or self.samyuktha.id)}, format='json'
        )
        self.assertEqual(response.status_code, 201, response.content)
        return response.data

    def make_document(self, workspace_id, **extra):
        body = {
            'title': 'Checklist',
            'content': 'first draft',
            'workspace': str(workspace_id),
            'created_by': str(self.samyuktha.id),
            **extra,
        }
        return self.client.post('/api/documents/', body, format='json')


class UserTests(ApiTestCase):
    def test_create_and_get(self):
        body = {'first_name': 'Mani', 'last_name': 'C', 'email': 'Mani@Example.com', 'phone': '9111111111'}
        response = self.client.post('/api/users/', body, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['email'], 'mani@example.com')
        self.assertEqual(response.data['full_name'], 'Mani C')
        fetched = self.client.get(f"/api/users/{response.data['id']}/")
        self.assertEqual(fetched.status_code, 200)

    def test_duplicate_email_is_409(self):
        body = {'first_name': 'X', 'last_name': 'Y', 'email': 'samyuktha@example.com', 'phone': '9222222222'}
        self.assertEqual(self.client.post('/api/users/', body, format='json').status_code, 409)

    def test_bad_email_and_phone_are_400(self):
        body = {'first_name': 'X', 'last_name': 'Y', 'email': 'nope', 'phone': 'abc'}
        response = self.client.post('/api/users/', body, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('email', response.data)
        self.assertIn('phone', response.data)

    def test_unknown_user_is_404(self):
        self.assertEqual(self.client.get('/api/users/00000000-0000-0000-0000-000000000000/').status_code, 404)


class WorkspaceTests(ApiTestCase):
    def test_create_adds_owner_as_admin_and_logs(self):
        workspace = self.make_workspace()
        self.assertEqual(workspace['member_count'], 1)
        member = WorkspaceMember.objects.get(workspace_id=workspace['id'])
        self.assertEqual((member.user, member.role), (self.samyuktha, 'admin'))
        self.assertTrue(AuditLog.objects.filter(model_name='Workspace', action='created').exists())

    def test_create_rolls_back_when_member_insert_fails(self):
        with mock.patch('api.views.WorkspaceMember.objects.create', side_effect=RuntimeError('boom')):
            with self.assertRaises(RuntimeError):
                self.client.post(
                    '/api/workspaces/', {'name': 'Ghost', 'owner': str(self.samyuktha.id)}, format='json'
                )
        self.assertFalse(Workspace.objects.filter(name='Ghost').exists())
        self.assertFalse(AuditLog.objects.filter(model_name='Workspace').exists())

    def test_detail_has_member_count(self):
        workspace = self.make_workspace()
        response = self.client.get(f"/api/workspaces/{workspace['id']}/")
        self.assertEqual(response.data['member_count'], 1)

    def test_add_and_list_members(self):
        workspace = self.make_workspace()
        url = f"/api/workspaces/{workspace['id']}/members/"
        added = self.client.post(url, {'user': str(self.arjun.id), 'role': 'editor'}, format='json')
        self.assertEqual(added.status_code, 201)
        listed = self.client.get(url)
        self.assertEqual([m['role'] for m in listed.data], ['admin', 'editor'])

    def test_duplicate_member_is_409(self):
        workspace = self.make_workspace()
        url = f"/api/workspaces/{workspace['id']}/members/"
        response = self.client.post(url, {'user': str(self.samyuktha.id)}, format='json')
        self.assertEqual(response.status_code, 409)

    def test_add_unknown_user_is_404(self):
        workspace = self.make_workspace()
        url = f"/api/workspaces/{workspace['id']}/members/"
        missing = '00000000-0000-0000-0000-000000000000'
        self.assertEqual(self.client.post(url, {'user': missing}, format='json').status_code, 404)

    def test_owner_cannot_change(self):
        workspace = self.make_workspace()
        body = {'name': 'Renamed', 'owner': str(self.arjun.id)}
        response = self.client.put(f"/api/workspaces/{workspace['id']}/", body, format='json')
        self.assertEqual(response.status_code, 400)
        body['owner'] = str(self.samyuktha.id)
        response = self.client.put(f"/api/workspaces/{workspace['id']}/", body, format='json')
        self.assertEqual((response.status_code, response.data['name']), (200, 'Renamed'))

    def test_inactive_workspace_rejects_members(self):
        workspace = self.make_workspace()
        Workspace.objects.filter(pk=workspace['id']).update(is_active=False)
        url = f"/api/workspaces/{workspace['id']}/members/"
        self.assertEqual(self.client.post(url, {'user': str(self.arjun.id)}, format='json').status_code, 400)

    def test_bad_role_is_400(self):
        workspace = self.make_workspace()
        url = f"/api/workspaces/{workspace['id']}/members/"
        self.assertEqual(self.client.post(url, {'user': str(self.arjun.id), 'role': 'boss'}, format='json').status_code, 400)

    def test_summary(self):
        workspace = self.make_workspace()
        doc = self.make_document(workspace['id']).data
        Comment.objects.create(document_id=doc['id'], author=self.samyuktha, content='nice')
        response = self.client.get(f"/api/workspaces/{workspace['id']}/summary/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            (response.data['document_count'], response.data['member_count'], response.data['comment_count']),
            (1, 1, 1),
        )


class DocumentTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.workspace = self.make_workspace()

    def test_create_makes_first_version_and_audit_log(self):
        response = self.make_document(self.workspace['id'])
        self.assertEqual(response.status_code, 201)
        versions = DocumentVersion.objects.filter(document_id=response.data['id'])
        self.assertEqual([v.version_number for v in versions], [1])
        log = AuditLog.objects.get(model_name='Document', object_id=response.data['id'])
        self.assertEqual((log.action, log.actor), ('created', self.samyuktha))

    def test_update_adds_version_and_logs_update(self):
        doc = self.make_document(self.workspace['id']).data
        body = {'title': 'Plan v2', 'content': 'second draft', 'workspace': self.workspace['id'], 'status': 'published'}
        response = self.client.put(f"/api/documents/{doc['id']}/", body, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data['status'], 'published')
        versions = list(DocumentVersion.objects.filter(document_id=doc['id']))
        self.assertEqual([v.version_number for v in versions], [1, 2])
        self.assertEqual(versions[1].content, 'second draft')
        actions = list(AuditLog.objects.filter(object_id=doc['id']).order_by('timestamp').values_list('action', flat=True))
        self.assertEqual(actions, ['created', 'updated'])

    def test_create_rolls_back_when_version_fails(self):
        with mock.patch('api.views.DocumentVersion.objects.create', side_effect=RuntimeError('boom')):
            with self.assertRaises(RuntimeError):
                self.make_document(self.workspace['id'])
        self.assertEqual(Document.objects.count(), 0)
        self.assertFalse(AuditLog.objects.filter(model_name='Document').exists())

    def test_viewer_cannot_write(self):
        self.client.post(
            f"/api/workspaces/{self.workspace['id']}/members/",
            {'user': str(self.arjun.id), 'role': 'viewer'}, format='json',
        )
        response = self.make_document(self.workspace['id'], created_by=str(self.arjun.id))
        self.assertEqual(response.status_code, 400)

    def test_author_cannot_change(self):
        doc = self.make_document(self.workspace['id']).data
        response = self.client.patch(
            f"/api/documents/{doc['id']}/", {'created_by': str(self.arjun.id)}, format='json'
        )
        self.assertEqual(response.status_code, 400)

    def test_created_by_is_required(self):
        body = {'title': 'x', 'content': 'y', 'workspace': self.workspace['id']}
        self.assertEqual(self.client.post('/api/documents/', body, format='json').status_code, 400)

    def test_list_filters(self):
        a = self.make_document(self.workspace['id'], title='Python guide', content='loops').data
        b = self.make_document(self.workspace['id'], title='Roadmap', content='python costs', status='published').data
        self.make_document(self.workspace['id'], title='Other', content='nothing')
        self.client.post(f"/api/documents/{a['id']}/tags/", {'tags': ['python']}, format='json')

        def ids(query):
            response = self.client.get(f'/api/documents/?{query}')
            self.assertEqual(response.status_code, 200, response.content)
            return {d['id'] for d in response.data}

        self.assertEqual(ids('search=python'), {a['id'], b['id']})
        self.assertEqual(ids('status=published'), {b['id']})
        self.assertEqual(ids('status=published,draft') & {a['id'], b['id']}, {a['id'], b['id']})
        self.assertEqual(ids('tag=Python'), {a['id']})
        self.assertEqual(len(ids(f"workspace={self.workspace['id']}")), 3)

    def test_list_bad_params_are_400(self):
        self.assertEqual(self.client.get('/api/documents/?status=bogus').status_code, 400)
        self.assertEqual(self.client.get('/api/documents/?workspace=nope').status_code, 400)

    def test_versions_in_order(self):
        doc = self.make_document(self.workspace['id']).data
        self.client.patch(f"/api/documents/{doc['id']}/", {'content': 'v2'}, format='json')
        response = self.client.get(f"/api/documents/{doc['id']}/versions/")
        self.assertEqual([v['version_number'] for v in response.data], [1, 2])

    def test_stats(self):
        doc = self.make_document(self.workspace['id']).data
        self.client.patch(f"/api/documents/{doc['id']}/", {'content': 'v2'}, format='json')
        Comment.objects.create(document_id=doc['id'], author=self.samyuktha, content='a')
        Comment.objects.create(document_id=doc['id'], author=self.samyuktha, content='b')
        response = self.client.get(f"/api/documents/{doc['id']}/stats/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            (response.data['version_count'], response.data['comment_count'], response.data['contributor_count']),
            (2, 2, 1),
        )

    def test_add_tags(self):
        doc = self.make_document(self.workspace['id']).data
        url = f"/api/documents/{doc['id']}/tags/"
        response = self.client.post(url, {'tags': ['python', 'django']}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['tags'], ['django', 'python'])
        self.assertEqual(Tag.objects.count(), 2)
        self.assertEqual(self.client.post(url, {'tags': []}, format='json').status_code, 400)

    def test_inactive_workspace_blocks_documents(self):
        Workspace.objects.filter(pk=self.workspace['id']).update(is_active=False)
        self.assertEqual(self.make_document(self.workspace['id']).status_code, 400)


class CommentTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        workspace = self.make_workspace()
        self.doc = self.make_document(workspace['id']).data
        self.other = self.make_document(workspace['id'], title='Other').data

    def post_comment(self, **extra):
        body = {'document': self.doc['id'], 'author': str(self.samyuktha.id), 'content': 'hello', **extra}
        return self.client.post('/api/comments/', body, format='json')

    def test_threaded_list(self):
        top = self.post_comment().data
        reply = self.post_comment(parent=top['id'], content='reply').data
        self.post_comment(parent=reply['id'], content='reply to reply')
        self.post_comment(content='second top')
        response = self.client.get(f"/api/comments/?document={self.doc['id']}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 2)
        first = response.data[0]
        self.assertEqual(first['author_name'], 'Samyuktha Test')
        self.assertEqual(first['replies'][0]['replies'][0]['content'], 'reply to reply')

    def test_parent_from_other_document_is_400(self):
        top = self.post_comment().data
        response = self.client.post(
            '/api/comments/',
            {'document': self.other['id'], 'content': 'x', 'parent': top['id']}, format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_list_needs_valid_document(self):
        self.assertEqual(self.client.get('/api/comments/').status_code, 400)
        self.assertEqual(self.client.get('/api/comments/?document=nope').status_code, 400)
        missing = '00000000-0000-0000-0000-000000000000'
        self.assertEqual(self.client.get(f'/api/comments/?document={missing}').status_code, 404)


class TagAndAuditTests(ApiTestCase):
    def test_tag_create_and_duplicate(self):
        self.assertEqual(self.client.post('/api/tags/', {'name': 'python'}, format='json').status_code, 201)
        self.assertEqual(self.client.post('/api/tags/', {'name': 'python'}, format='json').status_code, 409)
        self.assertEqual(self.client.post('/api/tags/', {'name': '  '}, format='json').status_code, 400)

    def test_audit_log_filters(self):
        workspace = self.make_workspace()
        self.make_document(workspace['id'])
        everything = self.client.get('/api/audit-logs/')
        self.assertEqual(len(everything.data), 2)
        by_actor = self.client.get(f'/api/audit-logs/?actor={self.samyuktha.id}')
        self.assertEqual(len(by_actor.data), 2)
        by_other = self.client.get(f'/api/audit-logs/?actor={self.arjun.id}')
        self.assertEqual(len(by_other.data), 0)
        self.assertEqual(len(self.client.get('/api/audit-logs/?from=2000-01-01&to=2999-01-01').data), 2)
        self.assertEqual(len(self.client.get('/api/audit-logs/?from=2999-01-01').data), 0)
        self.assertEqual(self.client.get('/api/audit-logs/?from=yesterday').status_code, 400)


class MiddlewareTests(ApiTestCase):
    def test_request_is_printed(self):
        with mock.patch('builtins.print') as fake_print:
            self.client.get('/api/users/')
        line = fake_print.call_args[0][0]
        self.assertTrue(line.startswith('GET /api/users/ 200 '))
        self.assertTrue(line.endswith('ms'))
