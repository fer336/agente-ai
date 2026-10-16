import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.admin import (
    get_authenticate_admin_use_case,
    get_committing_error_query_service,
    get_conversation_query_service,
    get_error_query_service,
    get_graph_state_query_service,
    get_kpi_name_catalog,
    get_kpi_query_service,
    get_run_query_service,
)
from app.api.dependencies.db import get_committing_db_session, get_db_session
from app.application.admin.authenticate_admin import AuthenticateAdminUseCase
from app.application.admin.conversation_queries import ConversationQueryService
from app.application.admin.error_queries import ErrorQueryService
from app.application.admin.graph_state_queries import GraphStateQueryService
from app.application.admin.kpi_names import KpiNameCatalog
from app.application.admin.kpi_queries import KpiQueryService
from app.application.admin.run_queries import RunQueryService
from app.config.settings import Settings


@pytest.mark.asyncio
async def test_get_authenticate_admin_use_case_returns_an_authenticate_admin_use_case():
    generator = get_committing_db_session()
    session: AsyncSession = await generator.__anext__()
    try:
        use_case = get_authenticate_admin_use_case(session, Settings())

        assert isinstance(use_case, AuthenticateAdminUseCase)
    finally:
        await session.close()
        with pytest.raises(StopAsyncIteration):
            await generator.__anext__()


@pytest.mark.asyncio
async def test_get_conversation_query_service_returns_a_conversation_query_service():
    generator = get_db_session()
    session: AsyncSession = await generator.__anext__()
    try:
        service = get_conversation_query_service(session)

        assert isinstance(service, ConversationQueryService)
    finally:
        await session.close()
        with pytest.raises(StopAsyncIteration):
            await generator.__anext__()


@pytest.mark.asyncio
async def test_get_error_query_service_returns_an_error_query_service():
    generator = get_db_session()
    session: AsyncSession = await generator.__anext__()
    try:
        service = get_error_query_service(session)

        assert isinstance(service, ErrorQueryService)
    finally:
        await session.close()
        with pytest.raises(StopAsyncIteration):
            await generator.__anext__()


@pytest.mark.asyncio
async def test_get_committing_error_query_service_returns_an_error_query_service():
    generator = get_committing_db_session()
    session: AsyncSession = await generator.__anext__()
    try:
        service = get_committing_error_query_service(session)

        assert isinstance(service, ErrorQueryService)
    finally:
        await session.close()
        with pytest.raises(StopAsyncIteration):
            await generator.__anext__()


@pytest.mark.asyncio
async def test_get_run_query_service_returns_a_run_query_service():
    generator = get_db_session()
    session: AsyncSession = await generator.__anext__()
    try:
        service = get_run_query_service(session)

        assert isinstance(service, RunQueryService)
    finally:
        await session.close()
        with pytest.raises(StopAsyncIteration):
            await generator.__anext__()


@pytest.mark.asyncio
async def test_get_graph_state_query_service_returns_a_graph_state_query_service():
    generator = get_db_session()
    session: AsyncSession = await generator.__anext__()
    try:
        service = get_graph_state_query_service(session)

        assert isinstance(service, GraphStateQueryService)
    finally:
        await session.close()
        with pytest.raises(StopAsyncIteration):
            await generator.__anext__()


@pytest.mark.asyncio
async def test_get_kpi_query_service_returns_a_kpi_query_service():
    generator = get_db_session()
    session: AsyncSession = await generator.__anext__()
    try:
        service = get_kpi_query_service(session)

        assert isinstance(service, KpiQueryService)
    finally:
        await session.close()
        with pytest.raises(StopAsyncIteration):
            await generator.__anext__()


def test_get_kpi_name_catalog_is_a_process_wide_singleton_built_without_bot_only_settings():
    get_kpi_name_catalog.cache_clear()
    try:
        first = get_kpi_name_catalog()

        assert isinstance(first, KpiNameCatalog)
        assert get_kpi_name_catalog() is first
    finally:
        get_kpi_name_catalog.cache_clear()
