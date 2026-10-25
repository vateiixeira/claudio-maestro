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
        'type': 'object', 'properties': {'work_item_id': {'type': 'integer'}}, 'additionalProperties': False})
    @_safe
    async def get_work(args):
        if args.get('work_item_id') is not None:
            return _result(host.get_work(session_id, args['work_item_id']))
        return _result(host.list_work(session_id))

    @tool('conclude', 'Registre uma entrega com evidências e testes realmente executados. O Maestro só libera a execução após o turno encerrar; sucesso segue para revisão.', {
        'type': 'object', 'properties': {
            'result_kind': {'type': 'string', 'enum': ['investigation', 'implementation', 'review']},
            'summary': {'type': 'string'}, 'evidence': {'type': 'array', 'items': {'type': 'string'}},
            'tests': {'type': 'array', 'items': {'type': 'string'}},
            'next_action': {'type': 'string'}, 'blockers': {'type': 'string'},
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

    return [delegate_work, get_work, conclude, request_decision]


def build_server(host, session_id: str):
    return create_sdk_mcp_server(name=SERVER_NAME, tools=build_tools(host, session_id))
