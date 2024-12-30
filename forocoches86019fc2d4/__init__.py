import time
import re
import aiohttp
import random
import asyncio
import logging
from bs4 import BeautifulSoup
from typing import AsyncGenerator
from datetime import datetime, timedelta
import pytz
from exorde_data import (
    Item,
    Content,
    Author,
    CreatedAt,
    Title,
    Url,
    Domain,
)

# GLOBAL VARIABLES
USER_AGENT_LIST = [
    'Mozilla/5.0 (iPad; CPU OS 12_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36',
]
DEFAULT_OLDNESS_SECONDS = 1200
DEFAULT_MAXIMUM_ITEMS = 25
DEFAULT_MIN_POST_LENGTH = 10

RANDOM_SKIP_TOPIC_PROBABILITY = 0.15

TIMESTAMP_PATTERN = r'^\d{2}:\d{2}$'  # made to match HH:MM format


async def fetch_page(session, url):
    async with session.get(url, headers={"User-Agent": random.choice(USER_AGENT_LIST)}, timeout=5.0) as response:
        return await response.text()


async def request_content_with_timeout(_url, _max_age):
    """
    Returns all relevant information from the news post
    :param _post_title: the title of the post to which the comment is linked
    :param _max_age: the maximum age we will allow for the post in seconds
    :param _url: the url of the post
    :return: the content of the post

    Once on the forum page look for this element:

    Once on the link for the topic post last's page, look for these elements:

    <div class="postbit_wrapper">
        <span class="postdate old"/> --> the post date of the item sous le format "Hoy HH:MM"
        <a onclick="copyToClipboard("https://"+window.location.hostname+"[end_of_link_to_post]"/>
        <tbody>
            <div class="squote"/> --> [OPTIONAL] WHEN PRESENT, this means the post is quoting a previous post: IGNORE THIS TEXT
            ... --> the rest is text that we want
        </tbody>
    </div>
    """
    try:
        async with aiohttp.ClientSession() as session:
            logging.info(f"[Forocoches] Fetching thread page: {_url}")
            response = await fetch_page(session, _url)
            soup = BeautifulSoup(response, 'html.parser')

            posts = soup.find_all("div", {"class": "postbit_wrapper"})
            logging.info(f"[Forocoches] Found {len(posts)} posts in the thread")
            for post in reversed(posts):  # loop backwards
                date = post.find("span", {"class": "postdate old"}).text
                simple_date = None
                post_date = None
                if not ("Hoy" in date):
                    break
                else:
                    simple_date = date.lstrip("Hoy").strip()  # remove the beginning of the string

                    if re.match(TIMESTAMP_PATTERN, simple_date):
                        post_date = convert_date_and_time_to_date_format(simple_date, 1)
                        # subtract 1 hour to the date
                        post_date = (datetime.strptime(post_date, "%Y-%m-%dT%H:%M:%S.00Z") - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S.00Z")
                        if check_for_max_age_with_correct_format(post_date, _max_age):
                            # proceed to scraping the post
                            #f_content = post.find("div", {"class": "postbit_legacy_style"}).text
                            sub_content = post.find_all("div", {"id": True})
                            quoted_content = post.find("div", {"class": "squote"})
                            if quoted_content:
                                quoted_content = quoted_content.text.strip()
                            else:
                                quoted_content = ""
                            content_holder = ""
                            for item in sub_content:
                                if "post_message" in item["id"]:
                                    content_holder = item.text.strip()

                            f_content = content_holder.lstrip(quoted_content)  # quoted content will be at the beginning
                            if f_content.strip() == "":  # post is empty (most likely an emoji, just skip it)
                                continue
                            
                            # the post title is the text of the first h1 tag on the page
                            try:
                                _post_title = soup.find("h1").text
                            except:
                                #skip the post if the title is not found
                                continue
                            content = f_content
                            link_to_post = post.find("a", {"onclick": True})["onclick"].lstrip("copyToClipboard(\"https://\"+window.location.hostname+\"").split("\"", 1)[0]
                            url = "https://forocoches.com/" + link_to_post

                            yield Item(
                                title=Title(_post_title),
                                content=Content(content),
                                created_at=CreatedAt(post_date),
                                url=Url(url),
                                domain=Domain("forocoches.com"))
                        else:
                            break
                    else:
                        break
    except Exception as e:
        logging.exception("Error:" + str(e))

async def parse_entries_with_timeout(_url, _max_age, max_nb_entries=20):
    try:
        logging.info(f"[Forocoches] Fetching forum page: {_url}")
        async with aiohttp.ClientSession() as session:
            response = await fetch_page(session, _url)
            # sleep for a random time to avoid being banned
            await asyncio.sleep(random.uniform(0.5, 1.5))
            soup = BeautifulSoup(response, 'html.parser')
            entries = soup.find("div", {"id": "container"})
            if not entries:
                return
            # <a href="showthread.php?p=487201954#post487201954">
            # only extract the URLs of the form showthread.php?p=487201954#post487201954
            entries = entries.find_all("a", {"href": re.compile("showthread.php\?p=\d+#post\d+")})
            entries_urls = []
            # https://forocoches.com/foro/ + entry["href"]
            for entry in entries:
                entries_urls.append("https://forocoches.com/foro/" + entry["href"])
            # remove entries_urls not of the exact form showthread.php?p=487201954#post487201954
            # select first 5 entries of the list and resolve them with timeout
            yielded_entries = 0
            for entry_url in entries_urls[:5]:
                async for item in request_content_with_timeout(entry_url, _max_age):
                    yield item
                    yielded_entries += 1
                    if yielded_entries >= max_nb_entries:
                        break
            
    except Exception as e:
        logging.exception("Error:" + str(e))

async def request_entries_with_timeout(_url, _max_age):
    """
    Extracts all card elements from the latest news section
    :param _max_age: the maximum age we will allow for the post in seconds
    :param _url: the url where we will find the latest posts
    :return: the card elements from which we can extract the relevant information
    """
    try:
        async with aiohttp.ClientSession() as session:
            response = await fetch_page(session, _url)
            soup = BeautifulSoup(response, 'html.parser')
            ## List a ll forums as <a href="forumdisplay.php?f=*">Forum Name</a>"
            forums = soup.find_all("a", {"href": re.compile("forumdisplay.php\?f=\d+")})

            forums_urls = []
            for forum in forums:
                forum_url = "https://forocoches.com/foro/" + forum["href"]
                forums_urls.append(forum_url)

            selected_forums = ['https://forocoches.com/foro/forumdisplay.php?f=2'] + random.sample(forums_urls, 3)

            # then resolve each forum with timeout, and parse the entries
            for forum_url in selected_forums:
                async for item in parse_entries_with_timeout(forum_url, _max_age):
                    yield item
    except Exception as e:
        logging.exception("Error:" + str(e))


def convert_date_and_time_to_date_format(_date, _delay):
    """
    "HH:MM" to standard checked against max age global param
    :param _date: HH:MM
    :return: correctly formatted date
    """
    _date += ":00"  # add the seconds
    date_today = datetime.now().date()
    year = date_today.year
    month = date_today.month
    day = date_today.day
    # Combine the components to form a date string in the format "YYYY-MM-DD"
    date_string = f"{year}-{month:02d}-{day:02d}"
    # Combine the date and time strings
    datetime_str = f"{date_string} {_date}"
    # Parse the combined string into a datetime object
    spanish_input_time = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M:%S")
    # Add 1 hour manually
    # Convert to UTC+0 (UTC) and format to the desired string format
    # Assume the French time as Europe/Paris timezone
    madrid_zone = pytz.timezone('Europe/Paris')
    spanish_input_time = madrid_zone.localize(spanish_input_time)
    # Convert to UTC+0 (UTC) and format to the desired string format
    input_time = spanish_input_time.astimezone(pytz.utc)
    formatted_time = input_time.strftime("%Y-%m-%dT%H:%M:%S.00Z")
    return formatted_time


def check_date_against_max_time(_date, _max_age, _time_delay):
    clean_date = convert_date_and_time_to_date_format(_date, _time_delay)
    return check_for_max_age_with_correct_format(clean_date, _max_age)


def check_for_max_age_with_correct_format(_date, _max_age):
    date_to_check = datetime.strptime(_date, "%Y-%m-%dT%H:%M:%S.00Z")
    now_time = datetime.strptime(datetime.strftime(datetime.now(pytz.utc), "%Y-%m-%dT%H:%M:%S.00Z"),
                                 "%Y-%m-%dT%H:%M:%S.00Z")
    if (now_time - date_to_check).total_seconds() <= _max_age:
        return (True, (now_time - date_to_check).total_seconds())
    else:
        return (False, (now_time - date_to_check).total_seconds())

def read_parameters(parameters):
    # Check if parameters is not empty or None
    if parameters and isinstance(parameters, dict):
        try:
            max_oldness_seconds = parameters.get("max_oldness_seconds", DEFAULT_OLDNESS_SECONDS)
        except KeyError:
            max_oldness_seconds = DEFAULT_OLDNESS_SECONDS

        try:
            maximum_items_to_collect = parameters.get("maximum_items_to_collect", DEFAULT_MAXIMUM_ITEMS)
        except KeyError:
            maximum_items_to_collect = DEFAULT_MAXIMUM_ITEMS

        try:
            min_post_length = parameters.get("min_post_length", DEFAULT_MIN_POST_LENGTH)
        except KeyError:
            min_post_length = DEFAULT_MIN_POST_LENGTH

    else:
        # Assign default values if parameters is empty or None
        max_oldness_seconds = DEFAULT_OLDNESS_SECONDS
        maximum_items_to_collect = DEFAULT_MAXIMUM_ITEMS
        min_post_length = DEFAULT_MIN_POST_LENGTH

    return max_oldness_seconds, maximum_items_to_collect, min_post_length


async def query(parameters: dict) -> AsyncGenerator[Item, None]:
    yielded_items = 0
    max_oldness_seconds, maximum_items_to_collect, min_post_length = read_parameters(parameters)
    logging.info(f"[forocoches.com] - Scraping ideas posted less than {max_oldness_seconds} seconds ago.")

    async for item in request_entries_with_timeout("https://forocoches.com/foro/", max_oldness_seconds):
        yielded_items += 1
        yield item
        logging.info(f"[forocoches.com] Found new item :\t {item}")
        if yielded_items >= maximum_items_to_collect:
            break
