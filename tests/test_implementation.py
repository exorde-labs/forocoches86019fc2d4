from forocoches86019fc2d4 import query
from exorde_data.models import Item
import logging
import pytest


@pytest.mark.asyncio
async def test_query():
    params = {
        "max_oldness_seconds": 120,
        "maximum_items_to_collect": 50
    }
    try:
        async for item in query(params):
            assert isinstance(item, Item)
            logging.info("Post Title: " + item.title)
            logging.info("Post Link: " + item.url)
            logging.info("Date of Post: " + item.created_at)
            logging.info("Post Content: " + item.content)
    except ValueError as e:
        logging.exception(f"Error: {str(e)}")


import asyncio
asyncio.run(test_query())

