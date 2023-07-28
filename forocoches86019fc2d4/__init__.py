"""
In this script we are going to collect data from Forocoches. All the latest posts on the forum are displayed here:

https://forocoches.com/

Times can be indicated in WEST UTC + 1 while on the topics themselves. On this page they seem to be indicated in UTC+1

On the initial link look for:

<tbody>
    <tr/> --> the first <tr/> tag corresponds to the columns declaration, scrape all the rest
    ...
    <tr/>
</tbody>

Every <tr/> tag is composed like this:

<tr>
    <td/> --> useless for us
    <td/> --> hour of post in UTC + 1 (Paris/Madrid Time)
    <td>
        <a/> --> the category to which belongs the post
        <a/> --> the title of the post, the href tag redirects to the 1st page of the topic
        <a/> --> [OPTIONAL] WHEN PRESENT, will redirect automatically to the LAST page of the topic
    </td>
</tr>

Once on the link for the topic post last's page, look for these elements:

<div class="postbit_wrapper">
    <span class="postdate old"/> --> the post date of the item sous le format "Hoy HH:MM"
    <tbody>
        <div class="squote"/> --> [OPTIONAL] WHEN PRESENT, this means the post is quoting a previous post: IGNORE THIS TEXT
        ... --> the rest is text that we want
    </tbody>
</div>
"""
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
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.1 Safari/605.1.15',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 13_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.1 Safari/605.1.15'
]
DEFAULT_OLDNESS_SECONDS = 1000
DEFAULT_MAXIMUM_ITEMS = 25
DEFAULT_MIN_POST_LENGTH = 10

RANDOM_SKIP_TOPIC_PROBABILITY = 0.15

TIMESTAMP_PATTERN = r'^\d{2}:\d{2}$'  # made to match HH:MM format


async def fetch_page(session, url):
    async with session.get(url, headers={"User-Agent": random.choice(USER_AGENT_LIST)}, timeout=8.0) as response:
        return await response.text()


async def request_content_with_timeout(_url, _post_title, _max_age):
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
            response = await fetch_page(session, _url)
            soup = BeautifulSoup(response, 'html.parser')

            posts = soup.find_all("div", {"class": "postbit_wrapper"})
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

                            content = _post_title + ". " + f_content
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


async def request_entries_with_timeout(_url, _max_age):
    """
    Extracts all card elements from the latest news section
    :param _max_age: the maximum age we will allow for the post in seconds
    :param _url: the url where we will find the latest posts
    :return: the card elements from which we can extract the relevant information

    Look for:

        <tbody>
            <tr/> --> the first <tr/> tag corresponds to the columns declaration, scrape all the rest
            ...
            <tr/>
        </tbody>

    Every <tr/> tag is composed this way:
        <tr>
            <td/> --> useless for us
            <td/> --> hour of post in UTC + 1 (Paris/Madrid Time)
            <td>
                <a/> --> the category to which belongs the post
                <a/> --> the title of the post, the href tag redirects to the 1st page of the topic
                <a/> --> [OPTIONAL] WHEN PRESENT, will redirect automatically to the LAST page of the topic
            </td>
        </tr>
    """
    try:
        async with aiohttp.ClientSession() as session:
            response = await fetch_page(session, _url)
            soup = BeautifulSoup(response, 'html.parser')
            entries = soup.find("table", {"class": "cajasnews"}).parent.parent.parent.find_all("tr", recursive=False)[2].find("td", recursive=False).find("table", recursive=False).find_all("tr", recursive=False)
            url_list = []
            title_list = []
            first_index = True
            for entry in entries:
                if first_index:
                    first_index = False
                    continue
                tds = entry.findChildren("td", recursive=False)
                if re.match(TIMESTAMP_PATTERN, tds[1].text):  # matches HH:MM format
                    if check_date_against_max_time(tds[1].text, _max_age, 2):  # respects our time window
                        a_elements = tds[2].findChildren("a", recursive=False)
                        if len(a_elements) == 3:  # we can skip directly to the last page
                            url = a_elements[2]["href"]  # the url to the last page of the topic
                        else:
                            url = a_elements[1]["href"]
                        title_list.append(a_elements[1].text)
                        url_list.append(url)
                    else:
                        break  # we reached an element that is too old, those that will follow will be too old as well

            async for item in parse_entry_for_elements(url_list, title_list, _max_age):
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
    input_time = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M:%S") - timedelta(hours=_delay)  # convert to UTC + 0
    # Convert to UTC+0 (UTC) and format to the desired string format
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
        return True
    else:
        return False


async def parse_entry_for_elements(_url_list, _title_list, _max_age):
    """
    Parses every element to find the relevant links & titles to the connected forums
    :param _url_list: The list of topic urls we need to collect from
    :param _title_list: The list of topic titles linked to the url list
    :param _max_age: The maximum age we will allow for the post in seconds
    :return: All the parameters we need to return an Item instance

    GET span.parent.find("a", {"class": "lien-jv topic-title stretched-link"})
    """
    try:
        for i in range(0, len(_url_list)):
            async for item in request_content_with_timeout("https://forocoches.com" + _url_list[i], _title_list[i],
                                                           _max_age):
                if item:
                    yield item
                else:
                    break  # if this item was not in the time bracket that interests us, the following ones will not be either
    except Exception as e:
        logging.exception("Error:" + str(e))


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

    async for item in request_entries_with_timeout("https://forocoches.com/", max_oldness_seconds):
        yielded_items += 1
        yield item
        logging.info(f"[forocoches.com] Found new post :\t {item.title}, posted at {item.created_at}, URL = {item.url}")
        if yielded_items >= maximum_items_to_collect:
            break