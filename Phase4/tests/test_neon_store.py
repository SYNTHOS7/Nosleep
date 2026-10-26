"""Transaction-aware PostgreSQL test double; live Neon is verified after connection."""
import copy
import json
import numpy as np
import pytest
from backend.storage.neon_store import NeonStore, NeonVectorStore, vector_literal
from backend.storage.graph_store import GraphStore
from test_cyber_and_hosted_storage import publish


class Database:
    def __init__(self):
        self.documents, self.vectors, self.users, self.roles = {}, {}, {}, {}
        self.fail_vectors = False
        self.calls = []
        self.rollbacks = 0
    def connect(self):
        return Connection(self)


class Connection:
    def __init__(self, db):
        self.db, self.result = db, []
    def __enter__(self):
        self.snapshot = copy.deepcopy((self.db.documents,self.db.vectors,self.db.users,self.db.roles))
        return self
    def __exit__(self, kind, value, trace):
        if kind:
            self.db.documents,self.db.vectors,self.db.users,self.db.roles = self.snapshot
            self.db.rollbacks += 1
    def cursor(self, name=None):
        return Cursor(self)
    def execute(self, statement, params=()):
        self.db.calls.append((statement, params))
        sql = ' '.join(statement.lower().split())
        if sql.startswith('insert into aegis.documents'):
            ws, doc, payload = params
            self.db.documents[ws,doc] = json.loads(payload)
        elif sql.startswith('delete from aegis.vectors'):
            ws, doc = params
            self.db.vectors = {key:value for key,value in self.db.vectors.items() if not (key[0]==ws and value[0]==doc)}
        elif sql.startswith('delete from aegis.documents'):
            ws, doc = params
            self.db.documents.pop((ws,doc),None)
            self.db.vectors = {key:value for key,value in self.db.vectors.items() if not (key[0]==ws and value[0]==doc)}
        elif sql.startswith('insert into aegis.vectors'):
            if self.db.fail_vectors:
                raise RuntimeError('simulated private SQL failure')
            ws,doc,cid,vec = params
            self.db.vectors[ws,cid] = (doc,json.loads(vec))
        elif sql.startswith('select workspace_id,document_id,batch'):
            self.result = [(ws,doc,payload) for (ws,doc),payload in sorted(self.db.documents.items())]
        elif sql.startswith('select chunk_id,'):
            vector,ws,allowed,_,_,limit = params
            query = np.array(json.loads(vector))
            self.result = []
            for (workspace,cid),(_,value) in self.db.vectors.items():
                if workspace==ws and (allowed is None or cid in allowed):
                    value = np.array(value)
                    score = float(np.dot(query,value)/(np.linalg.norm(query)*np.linalg.norm(value)))
                    self.result.append((cid,score))
            self.result = sorted(self.result,key=lambda row:(-row[1],row[0]))[:limit]
        elif sql.startswith('select platform_admin,disabled'):
            self.result = [self.db.users[params[0]]] if params[0] in self.db.users else []
        elif sql.startswith('select workspace_id,role'):
            self.result = [(ws,role) for (uid,ws),role in self.db.roles.items() if uid==params[0]]
        elif sql.startswith('insert into aegis.users'):
            self.db.users.setdefault(params[0],(False,False))
        elif sql.startswith('insert into aegis.memberships'):
            uid,ws,role=params
            self.db.roles[uid,ws]=role
        elif sql.startswith('delete from aegis.memberships'):
            self.db.roles.pop(tuple(params),None)
        elif sql.startswith('update aegis.users'):
            flag,uid=params
            self.db.users[uid]=(flag,self.db.users[uid][1])
        elif not sql.endswith('for update'):
            raise AssertionError('Unrecognized test query: '+sql)
        return self
    def fetchall(self):
        return list(self.result)
    def fetchone(self):
        return self.result[0] if self.result else None


class Cursor:
    def __init__(self, connection):
        self.connection=connection
    def __enter__(self):
        return self
    def __exit__(self,*args):
        pass
    def execute(self,*args):
        self.connection.execute(*args)
    def executemany(self,sql,rows):
        for row in rows:
            self.connection.execute(sql,row)
    def __iter__(self):
        return iter(self.connection.result)


def batch(workspace='one'):
    value=publish(GraphStore(),'Gateway accesses Database.',workspace=workspace)
    value.vectors={value.chunks[0].id:[1.0]+[0.0]*767}
    return value


def test_neon_publish_restart_query_edit_and_delete():
    db=Database()
    store=NeonStore(db.connect)
    value=batch()
    store.publish(value)
    store.publish(batch('other'))
    restored=list(NeonStore(db.connect).load_batches())
    assert {item.workspace_id for item in restored}=={'one','other'}
    vector=[1.0]+[0.0]*767
    assert store.query_vectors('one',vector,5)==[(value.chunks[0].id,1.0)]
    assert store.query_vectors('one',vector,5,[])==[]
    assert store.query_vectors('missing',vector,5)==[]
    old=next(iter(value.vectors))
    value.vectors={'new-chunk':vector}
    store.publish(value)
    assert store.query_vectors('one',vector,5)==[('new-chunk',1.0)]
    assert store.query_vectors('one',vector,5,[old])==[]
    store.delete_document('one',value.document.id)
    assert store.query_vectors('one',vector,5)==[]
    assert len(list(store.load_batches()))==1


def test_failed_vector_write_rolls_back_document_and_old_vectors():
    db=Database()
    store=NeonStore(db.connect)
    value=batch()
    store.publish(value)
    original=copy.deepcopy(db.documents)
    value.document.revision=2
    db.fail_vectors=True
    with pytest.raises(RuntimeError,match='Neon storage operation failed') as error:
        store.publish(value)
    assert 'private SQL' not in str(error.value)
    assert db.documents==original
    assert len(db.vectors)==1
    assert db.rollbacks==1


def test_memberships_are_parameterized_and_live():
    db=Database()
    store=NeonStore(db.connect)
    uid="user'; DROP TABLE users; --"
    store.set_access(uid,'alpha','editor',True)
    assert store.get_memberships(uid)=={'platform_admin':True,'disabled':False,'workspaces':{'alpha':'editor'}}
    assert all(uid not in sql for sql,_ in db.calls)
    store.set_access(uid,'alpha','remove',False)
    assert store.get_memberships(uid)['workspaces']=={}
    assert not store.get_memberships(uid)['platform_admin']


def test_neon_vector_cache_reset_never_deletes_persistent_data():
    db=Database()
    vector_store=NeonVectorStore(db.connect)
    value=batch()
    vector_store.persistence.publish(value)
    vector_store.cache_vectors('one',value.vectors)
    vector_store.clear()
    assert vector_store.get_vectors('one')=={}
    assert len(vector_store.query('one',[1.0]+[0.0]*767))==1


def test_invalid_vector_is_rejected_before_publication():
    db=Database()
    value=batch()
    value.vectors={'bad':[float('nan')]*768}
    with pytest.raises(ValueError):
        NeonStore(db.connect).publish(value)
    assert not db.documents
    for vector in ([],[0.0]*768):
        with pytest.raises(ValueError):
            vector_literal(vector)
