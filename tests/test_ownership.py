from __future__ import annotations

from copy import deepcopy

import pytest

from pinkydocs.supabase_service import SupabaseService


class Response:
    def __init__(self, data):
        self.data = data


class Query:
    def __init__(self, client, table):
        self.client = client
        self.table_name = table
        self.action = "select"
        self.filters = []
        self.values = None

    def select(self, *_columns):
        self.action = "select"
        return self

    def eq(self, key, value):
        self.filters.append(("eq", key, str(value)))
        return self

    def in_(self, key, values):
        self.filters.append(("in", key, {str(value) for value in values}))
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args):
        return self

    def delete(self):
        self.action = "delete"
        return self

    def insert(self, values):
        self.action = "insert"
        self.values = values
        return self

    def update(self, values):
        self.action = "update"
        self.values = values
        return self

    def execute(self):
        self.client.queries.append((self.table_name, self.action, deepcopy(self.filters)))
        rows = self.client.tables.setdefault(self.table_name, [])

        def matches(row):
            for mode, key, value in self.filters:
                actual = str(row.get(key))
                if mode == "eq" and actual != value:
                    return False
                if mode == "in" and actual not in value:
                    return False
            return True

        if self.action == "select":
            return Response([deepcopy(row) for row in rows if matches(row)])
        if self.action == "delete":
            removed = [row for row in rows if matches(row)]
            self.client.tables[self.table_name] = [row for row in rows if not matches(row)]
            return Response(removed)
        if self.action == "insert":
            values = self.values if isinstance(self.values, list) else [self.values]
            self.client.tables[self.table_name].extend(deepcopy(values))
            return Response(values)
        if self.action == "update":
            for row in rows:
                if matches(row):
                    row.update(self.values)
            return Response([])
        raise AssertionError(self.action)


class Bucket:
    def __init__(self, storage):
        self.storage = storage

    def remove(self, paths):
        self.storage.removed.extend(paths)
        return Response([])


class Storage:
    def __init__(self):
        self.removed = []

    def from_(self, _bucket):
        return Bucket(self)


class FakeSupabase:
    def __init__(self, tables):
        self.tables = deepcopy(tables)
        self.queries = []
        self.storage = Storage()

    def table(self, table_name):
        return Query(self, table_name)


def make_service(settings, tables):
    client = FakeSupabase(tables)
    return SupabaseService(client, settings), client


def test_owned_user_can_load_only_their_document_chunks(settings):
    service, client = make_service(settings, {
        "documents": [
            {"id": "doc-a", "user_id": "user-a", "display_name": "A policy", "original_filename": "a.txt", "file_type": "txt"},
            {"id": "doc-b", "user_id": "user-b", "display_name": "B policy", "original_filename": "b.txt", "file_type": "txt"},
        ],
        "document_chunks": [
            {"document_id": "doc-a", "user_id": "user-a", "chunk_index": 0, "content": "Annual leave is 18 days."},
            {"document_id": "doc-b", "user_id": "user-b", "chunk_index": 0, "content": "Private note."},
        ],
    })
    chunks = service.get_owned_chunks("user-a", ["doc-a"])
    assert len(chunks) == 1
    assert chunks[0].content == "Annual leave is 18 days."
    query = next(q for q in client.queries if q[0] == "document_chunks")
    assert ("eq", "user_id", "user-a") in query[2]


def test_user_cannot_retrieve_another_users_document_chunks(settings):
    service, client = make_service(settings, {
        "documents": [
            {"id": "doc-b", "user_id": "user-b", "display_name": "Secret", "file_type": "txt"},
        ],
        "document_chunks": [
            {"document_id": "doc-b", "user_id": "user-b", "chunk_index": 0, "content": "Secret data"},
        ],
    })
    with pytest.raises(PermissionError, match="unavailable"):
        service.get_owned_chunks("user-a", ["doc-b"])
    assert not any(query[0] == "document_chunks" for query in client.queries)


def test_conversation_messages_are_owner_scoped(settings):
    service, client = make_service(settings, {
        "conversations": [{"id": "conv-b", "user_id": "user-b", "title": "Private"}],
        "messages": [{"id": "m1", "user_id": "user-b", "conversation_id": "conv-b", "role": "assistant", "content": "Secret"}],
    })
    with pytest.raises(PermissionError, match="unavailable"):
        service.get_messages("user-a", "conv-b")
    assert not any(query[0] == "messages" for query in client.queries)


def test_user_cannot_delete_another_users_document_or_storage_object(settings):
    service, client = make_service(settings, {
        "documents": [{"id": "doc-b", "user_id": "user-b", "storage_path": "user-b/doc-b/original.txt"}],
    })
    with pytest.raises(PermissionError, match="unavailable"):
        service.delete_document("user-a", "doc-b")
    assert client.storage.removed == []
    assert client.tables["documents"][0]["id"] == "doc-b"


def test_conversation_selection_rejects_foreign_document_before_mutation(settings):
    service, client = make_service(settings, {
        "conversations": [{"id": "conv-a", "user_id": "user-a", "title": "My chat"}],
        "documents": [{"id": "doc-b", "user_id": "user-b", "display_name": "Secret"}],
        "conversation_documents": [],
    })
    with pytest.raises(PermissionError, match="unavailable"):
        service.set_conversation_documents("user-a", "conv-a", ["doc-b"])
    assert client.tables["conversation_documents"] == []
    assert not any(query[0] == "conversation_documents" for query in client.queries)


def test_conversation_creation_validates_document_ownership(settings):
    service, client = make_service(settings, {
        "documents": [{"id": "doc-b", "user_id": "user-b"}],
        "conversations": [],
    })
    with pytest.raises(PermissionError):
        service.create_conversation("user-a", "My chat", ["doc-b"])
    assert client.tables["conversations"] == []
