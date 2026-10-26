"""Work MCP: actor identity is captured by the server, never supplied by the model."""
import json
import logging
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

from . import store

logger = logging.getLogger(__name__)
SERVER_NAME = 'maestro_work'


def _result(value: Any, *, error: bool = False) -> dict:
    return {'content': [{'type': 'text', 'text': json.dumps(value, ensure_ascii=False)}], **({'is_error': True} if error else {})}


def _safe(handler):
    async def wrapped(args):
        try:
            return await handler(args)
        except store.WorkError as error:
            return _result(str(error), error=True)
        except Exception:
            logger.exception('Falha em uma ferramenta de trabalho')
            return _result('Não foi possível registrar esta ação agora.', error=True)
    return wrapped


def build_tools(host, session_id: str):
    @tool('delegate_work', 'Delegue uma issue focada a uma sessão própria do projeto. Retorna a tarefa aceita; não espera o executor.', {
        'type': 'object', 'properties': {
            'title': {'type': 'string'}, 'objective': {'type': 'string'}, 'acceptance': {'type': 'string'},
            'role': {'type': 'string', 'enum': ['investigator', 'implementer']},
            'source': {'type': 'string'}, 'source_instance': {'type': 'string'},
            'source_project': {'type': 'string'}, 'external_id': {'type': 'string'},
            'source_revision': {'type': 'string'}, 'priority': {'type': 'string', 'enum': list(store.PRIORITIES)},
        }, 'required': ['title', 'objective'], 'additionalProperties': False})
    @_safe
    async def delegate_work(args):
        item = await host.delegate(session_id, **args)
        return _result({'accepted': True, 'work_item_id': item.id, 'revision': item.revision, 'status': item.status})

    @tool('get_work', 'Consulte a tarefa e as tentativas deste projeto; omita work_item_id para a lista compacta.', {
        'type': 'object', 'properties': {'work_item_id': {'type': 'integer'}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 200}, 'offset': {'type': 'integer', 'minimum': 0}}, 'additionalProperties': False})
    @_safe
    async def get_work(args):
        if args.get('work_item_id') is not None:
            return _result(host.get_work(session_id, args['work_item_id']))
        return _result(host.list_work(session_id, limit=args.get('limit', 25), offset=args.get('offset', 0)))

    @tool('conclude', 'Registre uma entrega com evidências e testes realmente executados. O Maestro só libera a execução após o turno encerrar; sucesso segue para revisão.', {
        'type': 'object', 'properties': {
            'result_kind': {'type': 'string', 'enum': ['investigation', 'implementation', 'review']},
            'summary': {'type': 'string'}, 'evidence': {'type': 'array', 'items': {'type': 'string'}},
            'tests': {'type': 'array', 'items': {'type': 'string'}},
            'next_action': {'type': 'string'}, 'blockers': {'type': 'string'},
            'delivery_type': {'type': 'string', 'enum': ['investigation_complete', 'implementation_complete', 'technical_followup', 'product_decision', 'policy_blocked']},
        }, 'required': ['result_kind', 'summary'], 'additionalProperties': False})
    @_safe
    async def conclude(args):
        await host.conclude(session_id, **args)
        return _result({'recorded': True, 'finalization': 'after_turn_end'})

    @tool('request_decision', 'Registre a pergunta humana concreta e suas evidências. Não use para dúvidas que podem ser investigadas no código.', {
        'type': 'object', 'properties': {'question': {'type': 'string'}, 'evidence': {'type': 'array', 'items': {'type': 'string'}}},
        'required': ['question'], 'additionalProperties': False})
    @_safe
    async def request_decision(args):
        await host.request_decision(session_id, **args)
        return _result({'recorded': True, 'waiting_for': 'human_decision'})

    @tool('collect_source', 'Colete metadados numa sessão própria normal do projeto; o CTO recebe só referências compactas.', {
        'type': 'object', 'properties': {
            'source': {'type': 'string', 'enum': ['sentry', 'kbgen']},
            'source_instance': {'type': 'string', 'maxLength': 200},
            'source_project': {'type': 'string', 'maxLength': 200},
            'query': {'type': 'string', 'maxLength': 2000},
        }, 'required': ['source', 'source_instance', 'source_project'], 'additionalProperties': False})
    @_safe
    async def collect_source(args):
        return _result(await host.collect_source(session_id, **args))

    @tool('get_source_metadata', 'Consulte a revisão local de um id externo somente no escopo capturado desta coleta, sem carregar corpo ou evidência.', {
        'type': 'object', 'properties': {'external_id': {'type': 'string', 'maxLength': 200}},
        'required': ['external_id'], 'additionalProperties': False})
    @_safe
    async def get_source_metadata(args):
        return _result(host.source_metadata(session_id, args['external_id']))

    @tool('publish_collection', 'Publique uma página de metadados no escopo capturado desta coleta. next_cursor=null comprova fim da consulta.', {
        'type': 'object', 'properties': {
            'items': {'type': 'array', 'maxItems': 25, 'items': {
                'type': 'object', 'properties': {
                    'external_id': {'type': 'string', 'maxLength': 200},
                    'title': {'type': 'string', 'maxLength': 160},
                    'priority': {'type': 'string', 'enum': list(store.PRIORITIES)},
                    'source_revision': {'type': 'string', 'maxLength': 200},
                    'url': {'type': 'string', 'maxLength': 1000},
                    'expected_revision': {'type': 'integer', 'minimum': 1},
                }, 'required': ['external_id', 'title', 'source_revision', 'url'], 'additionalProperties': False}},
            'cursor': {'type': 'string', 'maxLength': 500},
            'next_cursor': {'type': ['string', 'null'], 'maxLength': 500},
        }, 'required': ['items', 'cursor', 'next_cursor'], 'additionalProperties': False})
    @_safe
    async def publish_collection(args):
        return _result(await host.publish_collection(session_id, **args))

    @tool('start_work', 'Priorize e admita uma tarefa do backlog; exige a revisão atual.', {
        'type': 'object', 'properties': {'work_item_id': {'type': 'integer'}, 'expected_revision': {'type': 'integer', 'minimum': 1}},
        'required': ['work_item_id', 'expected_revision'], 'additionalProperties': False})
    @_safe
    async def start_work(args):
        return _result(host.start_backlog(session_id, args['work_item_id'], expected_revision=args['expected_revision']))

    @tool('reevaluate_work', 'Reabra a entrada da mesma issue após mudança de código, com motivo e referência concretos. Conserva evidências antigas.', {
        'type': 'object', 'properties': {
            'work_item_id': {'type': 'integer'}, 'expected_revision': {'type': 'integer', 'minimum': 1},
            'reason': {'type': 'string', 'maxLength': 1000}, 'code_reference': {'type': 'string', 'maxLength': 500},
        }, 'required': ['work_item_id', 'expected_revision', 'reason', 'code_reference'], 'additionalProperties': False})
    @_safe
    async def reevaluate_work(args):
        from dataclasses import asdict
        return _result(asdict(host.reevaluate(session_id, args['work_item_id'], **{k: v for k, v in args.items() if k != 'work_item_id'})))

    @tool('get_work_evidence', 'Leia evidência privada de UMA tarefa sob demanda. Não busque os corpos de um lote.', {
        'type': 'object', 'properties': {'work_item_id': {'type': 'integer'}},
        'required': ['work_item_id'], 'additionalProperties': False})
    @_safe
    async def get_work_evidence(args):
        item_id = args['work_item_id']
        value = host.get_work(session_id, item_id)
        value['dossier'] = host.dossier(item_id)
        for attempt in value['attempts']:
            attempt['result'] = host.result(attempt['id'])
        return _result(value)

    return [delegate_work, get_work, conclude, request_decision, collect_source,
            publish_collection, start_work, reevaluate_work, get_work_evidence, get_source_metadata]


def build_server(host, session_id: str):
    return create_sdk_mcp_server(name=SERVER_NAME, tools=build_tools(host, session_id))
