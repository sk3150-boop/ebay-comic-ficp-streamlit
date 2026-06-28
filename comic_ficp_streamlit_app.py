from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
from contextlib import contextmanager
import hmac
import io
import json
import hashlib
import math
import os
import re
import secrets
import sqlite3
import time
from dataclasses import dataclass, field
from functools import lru_cache
from html import unescape
from pathlib import Path
from typing import Callable, Iterable, Optional
from urllib.parse import unquote, urlparse

import pandas as pd

try:
    import requests
except ImportError:  # pragma: no cover - runtime dependency is listed separately.
    requests = None

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover - runtime dependency is listed separately.
    BeautifulSoup = None

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - optional browser-rendering dependency.
    sync_playwright = None

try:
    from cryptography.fernet import Fernet
except ImportError:  # pragma: no cover - deployment dependency is listed separately.
    Fernet = None


APP_TITLE = "eBay Manga CSV FICP Assistant"
AUTOFILL_MARKER_START = "<!-- comic-ficp-autofill -->"
AUTOFILL_MARKER_END = "<!-- /comic-ficp-autofill -->"
API_KEY_STORE_PATH = Path(os.getenv("APPDATA") or Path.home()) / "ComicFicpStreamlit" / "api_keys.json"
PUBLIC_MODE_ENV = "COMIC_FICP_PUBLIC_MODE"
PUBLIC_DATABASE_URL_ENV = "COMIC_FICP_DATABASE_URL"
PUBLIC_KEY_SECRET_ENV = "COMIC_FICP_KEY_ENCRYPTION_SECRET"
PUBLIC_SESSION_USER_KEY = "comic_ficp_public_user"
PUBLIC_AUTH_DB_FALLBACK_PATH = API_KEY_STORE_PATH.with_name("public_auth.sqlite3")
UPLOAD_CACHE_RAW_PATH = API_KEY_STORE_PATH.with_name("last_uploaded_csv.bin")
UPLOAD_CACHE_META_PATH = API_KEY_STORE_PATH.with_name("last_uploaded_csv.json")
PROCESSED_CACHE_DF_PATH = API_KEY_STORE_PATH.with_name("last_processed_dataframe.pkl")
PROCESSED_CACHE_META_PATH = API_KEY_STORE_PATH.with_name("last_processed_dataframe.json")
DEFAULT_EXCHANGE_RATE_JPY_PER_USD = 155.0
DEFAULT_FUEL_SURCHARGE_PERCENT = 35.0
DEFAULT_FICP_ZONE = "E"
DEFAULT_BOOK_WEIGHT_G = 200
DEFAULT_PACKAGING_WEIGHT_KG = 0.60
DEFAULT_MAX_BOOK_COUNT_FOR_EXPORT = 40
DEFAULT_FREE_SHIPPING_PROFILE_NAME = "Free Shipping Policy Fedex"
FREE_SHIPPING_PROFILE_OPTIONS = [
    "Free Shipping Policy Fedex",
    "Free Shipping Policy",
]
DEFAULT_FREE_SHIPPING_MARKUP_PERCENT = 10.0
EBAY_ITEM_SPECIFIC_VALUE_MAX_CHARS = 65
REVIEW_TABLE_HEIGHT_PX = 780
REVIEW_TABLE_ROW_HEIGHT_PX = 148
REVIEW_TABLE_IMAGE_WIDTH_PX = 190
DEFAULT_DIMENSIONAL_DIVISOR_CM = 5000
DEFAULT_MANGA_HEIGHT_CM = 18.2
DEFAULT_MANGA_WIDTH_CM = 12.8
DEFAULT_MANGA_THICKNESS_CM = 1.6
DEFAULT_BOX_PADDING_CM = 4.0
DEFAULT_BOX_EXTRA_HEIGHT_CM = 4.0
WEIGHT_STANDARD_SHONEN_G = 180
WEIGHT_STANDARD_SHOJO_G = 175
WEIGHT_STANDARD_SEINEN_G = 220
WEIGHT_SMALL_BUNKO_G = 150
WEIGHT_LARGE_EDITION_G = 320
DEFAULT_AI_PROVIDER = "gemini"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash-lite"
DEFAULT_OPENAI_MODEL = "gpt-5.4-mini"
GEMINI_MODEL_OPTIONS = [
    ("gemini-2.5-flash-lite", "Gemini 2.5 Flash-Lite (low cost / fast)"),
    ("gemini-2.5-flash", "Gemini 2.5 Flash (balanced)"),
    ("gemini-2.5-pro", "Gemini 2.5 Pro (higher accuracy)"),
    ("gemini-3.1-flash-lite", "Gemini 3.1 Flash-Lite (new stable / fast)"),
    ("gemini-3-flash-preview", "Gemini 3 Flash Preview (new / balanced)"),
    ("gemini-3.5-flash", "Gemini 3.5 Flash (frontier stable)"),
    ("gemini-3.1-pro-preview", "Gemini 3.1 Pro Preview (highest accuracy candidate)"),
    ("custom", "Custom model name"),
]
OPENAI_MODEL_OPTIONS = [
    ("gpt-5.4-mini", "GPT-5.4 mini (recommended balance)"),
    ("gpt-5.4-nano", "GPT-5.4 nano (low cost)"),
    ("gpt-5.4", "GPT-5.4 (higher accuracy)"),
    ("gpt-5.5", "GPT-5.5 (latest high accuracy)"),
    ("gpt-5.4-pro", "GPT-5.4 pro (high accuracy / high cost)"),
    ("gpt-5.5-pro", "GPT-5.5 pro (highest accuracy / high cost)"),
    ("custom", "Custom model name"),
]

DEFAULT_SPECIFIC_COLUMNS = [
    "C:Brand",
    "C:Language",
    "C:Publisher",
    "C:Author",
    "C:Artist/Writer",
    "C:Format",
    "C:Type",
    "C:Country/Region of Manufacture",
    "C:Series",
    "C:Genre",
    "C:Grade",
    "C:Intended Audience",
    "C:Book Title",
    "C:Unit Type",
]

SPECIFIC_COLUMNS = DEFAULT_SPECIFIC_COLUMNS

SPECIFIC_DISPLAY_LABELS = {
    "C:Brand": "Brand",
    "C:Language": "Language",
    "C:Publisher": "Publisher",
    "C:Author": "Author",
    "C:Format": "Format",
    "C:Type": "Type",
    "C:Country/Region of Manufacture": "Country",
    "C:Series": "Series",
    "C:Genre": "Genre",
    "C:Grade": "Grade",
    "C:Book Title": "Book Title",
    "C:Original Language": "Original Language",
    "C:Narrative Type": "Narrative Type",
    "C:Intended Audience": "Intended Audience",
    "C:Signed": "Signed",
    "C:Personalized": "Personalized",
    "C:Inscribed": "Inscribed",
    "C:Ex Libris": "Ex Libris",
    "C:Topic": "Topic",
    "C:Features": "Features",
    "C:Edition": "Edition",
    "C:Tradition": "Tradition",
    "C:Unit of Sale": "Unit of Sale",
    "C:Series Title": "Series Title",
    "C:Story Title": "Story Title",
    "C:Artist/Writer": "Artist/Writer",
    "C:Style": "Style",
    "C:Number of Books": "Number of Books",
    "C:Number of Items": "Number of Items",
    "C:Unit Quantity": "Unit Quantity",
    "C:Unit Type": "Unit Type",
    "C:Item Weight": "Item Weight",
    "C:ISBN": "ISBN",
    "C:Publication Year": "Publication Year",
    "C:Vintage": "Vintage",
    "C:Character": "Character",
    "C:Universe": "Universe",
    "C:Era": "Era",
    "C:Material": "Material",
    "C:Custom Bundle": "Custom Bundle",
    "C:Convention/Event": "Convention/Event",
    "C:Autograph Authentication": "Autograph Authentication",
    "C:Autograph Authentication Number": "Autograph Authentication Number",
    "C:Certification Number": "Certification Number",
    "C:California Prop 65 Warning": "California Prop 65 Warning",
}

FICP_ZONES = [
    "A",
    "D",
    "E",
    "F",
    "G",
    "H",
    "I",
    "J",
    "K",
    "M",
    "N",
    "O",
    "Q",
    "R",
    "S",
    "T",
    "U",
    "V",
    "W",
    "X",
    "Y",
    "Z",
]

ZONE_LABELS = {
    "A": "Zone A",
    "D": "Zone D",
    "E": "Zone E - U.S. western region in the PDF",
    "F": "Zone F - U.S. other / Canada / Puerto Rico in the PDF",
    "G": "Zone G - Latin America / Caribbean examples",
    "H": "Zone H - selected Europe examples",
    "I": "Zone I - selected Europe / Middle East examples",
    "J": "Zone J - selected Africa / South Asia examples",
    "K": "Zone K - China South examples",
    "M": "Zone M - UK / France / Germany / Spain examples",
    "N": "Zone N - Vietnam example",
    "O": "Zone O",
    "Q": "Zone Q",
    "R": "Zone R - Thailand example",
    "S": "Zone S - Philippines example",
    "T": "Zone T",
    "U": "Zone U - Australia / New Zealand example",
    "V": "Zone V - Hong Kong example",
    "W": "Zone W - China excluding South example",
    "X": "Zone X - Taiwan example",
    "Y": "Zone Y - Singapore example",
    "Z": "Zone Z - South Korea example",
}

# FedEx International Connect Plus Export (Japan, JPY)
# Source: the attached FedEx PDFs supplied with the request. The PDF header order is
# A, D, E, F, G, ...; this means Zone E is 2,179 JPY and Zone F is 2,206 JPY
# at 0.5 kg in the extracted contract table.
FICP_STANDARD_RATE_TEXT = """
0.5:2587,5584,2179,2206,3439,2947,2993,2985,2155,2212,1582,2175,1783,1491,1793,2484,1931,1695,2155,1969,1644,1998
1.0:3487,6257,2443,2493,3892,3338,3318,3348,2238,2573,1658,2589,1874,1569,1950,2628,2171,1781,2238,2070,1734,2085
1.5:3996,7333,2688,2778,4942,3727,3647,4122,2295,2932,1660,3112,1984,1746,2022,2769,2396,1866,2295,2155,1810,2170
2.0:4331,8100,2942,3041,5689,4187,4196,4495,2487,3294,1795,3437,2145,1888,2187,3040,2646,2022,2487,2335,1957,2351
2.5:4671,8866,3199,3308,6444,4651,4747,4870,2683,3659,1931,3762,2307,2030,2352,3314,2896,2181,2683,2519,2105,2536
3.0:5005,9576,3449,3596,8376,4932,4751,6443,2875,4058,2065,4729,2470,2173,2518,3633,3128,2337,2875,2699,2254,2718
3.5:5339,10286,3698,3863,9315,5320,4955,7284,3067,4414,2202,5039,2633,2317,2684,3952,3380,2493,3067,2879,2402,2899
4.0:5673,10996,4139,4324,10179,5782,5440,8019,3259,4798,2338,5387,2796,2460,2851,4271,3614,2649,3259,3059,2551,3081
4.5:6008,11706,4579,4786,11043,6245,5925,8754,3451,5181,2474,5734,2959,2604,3017,4590,3847,2805,3451,3239,2700,3262
5.0:6342,12415,5020,5248,11907,6707,6410,9489,3642,5565,2610,6082,3122,2747,3183,4909,4080,2961,3642,3420,2848,3443
5.5:6345,13656,5419,5556,14133,7485,7138,12528,3661,6583,2611,6914,3389,3174,3231,4912,4329,3154,3661,3429,3001,3647
6.0:6590,14423,5591,5733,14522,7794,7343,13049,3802,6855,2730,7302,3542,3318,3377,5061,4572,3276,3802,3562,3137,3788
6.5:6836,15189,5763,5911,14912,8102,7549,13570,3944,7126,2848,7690,3696,3462,3524,5210,4815,3398,3944,3694,3273,3929
7.0:7081,15955,5936,6088,15302,8411,7754,14091,4085,7397,2967,8078,3850,3606,3670,5359,5058,3520,4085,3827,3410,4070
7.5:7326,16722,6108,6265,15691,8719,7959,14611,4227,7669,3085,8466,4004,3750,3817,5507,5301,3642,4227,3959,3546,4211
8.0:7572,17488,6280,6443,16081,9028,8164,15132,4368,7940,3204,8854,4157,3894,3964,5656,5544,3764,4368,4092,3682,4352
8.5:7817,18255,6452,6620,16470,9336,8370,15653,4510,8211,3322,9242,4311,4038,4110,5805,5787,3886,4510,4225,3818,4493
9.0:8062,19021,6624,6797,16860,9645,8575,16174,4652,8482,3441,9630,4465,4182,4257,5954,6030,4008,4652,4357,3954,4634
9.5:8099,19214,7821,8193,20378,10794,9877,19533,4793,9666,3559,10310,4619,4326,4403,6103,6344,4130,4793,4490,4091,4775
10.0:8338,19958,8019,8402,20838,11128,10108,20142,4935,9966,3678,10709,4773,4470,4550,6252,6589,4252,4935,4622,4227,4916
10.5:8552,20559,8232,8640,21353,11357,10362,20923,5062,10170,3757,11031,4876,4567,4648,6377,6788,4362,5062,4741,4318,5043
11.0:8767,21161,8444,8877,21869,11585,10616,21704,5189,10375,3836,11354,4978,4663,4746,6502,6986,4471,5189,4860,4409,5169
11.5:8981,21762,8656,9115,22384,11814,10870,22484,5315,10580,3916,11676,5081,4759,4845,6628,7185,4580,5315,4979,4500,5296
12.0:9195,22363,8869,9353,22900,12042,11124,23265,5442,10784,3995,11999,5184,4856,4943,6753,7383,4690,5442,5098,4592,5422
12.5:9410,22964,9479,10129,31909,13286,12809,31100,6901,11967,7275,12434,7517,8715,7363,9024,8334,5870,7120,7815,8950,7366
13.0:9624,23565,9701,10380,32612,13534,13095,32110,7058,12190,7416,12759,7664,8885,7507,9189,8552,6004,7282,7993,9124,7534
13.5:9839,24166,9923,10631,33314,13781,13381,33120,7215,12413,7558,13085,7810,9054,7650,9353,8770,6138,7444,8171,9298,7702
14.0:10053,24767,10144,10882,34017,14028,13667,34130,7373,12636,7700,13410,7956,9224,7793,9517,8989,6272,7607,8349,9473,7870
14.5:10268,25368,10366,11133,34719,14276,13953,35140,7530,12859,7841,13736,8103,9394,7937,9681,9207,6406,7769,8527,9647,8038
15.0:10482,25969,10588,11384,35421,14523,14239,36149,7687,13081,7983,14061,8249,9563,8080,9846,9425,6539,7931,8705,9821,8206
15.5:10696,26570,10809,11636,36124,14771,14526,37159,7844,13304,8125,14387,8396,9733,8224,10010,9643,6673,8093,8883,9996,8373
16.0:10911,27171,11582,12374,36122,16258,15502,37166,8002,14725,8266,14386,8542,9903,8367,10174,10134,6807,8256,9061,10170,8541
16.5:11125,27772,11815,12635,36811,16526,15801,38150,8159,14968,8408,14705,8688,10073,8510,10339,10358,6941,8418,9239,10344,8709
17.0:11340,28374,12047,12897,37500,16794,16101,39133,8316,15210,8550,15023,8835,10242,8654,10503,10582,7074,8580,9417,10518,8877
17.5:11554,28975,12280,13158,38189,17061,16400,40116,8473,15453,8691,15341,8981,10412,8797,10667,10806,7208,8742,9595,10693,9045
18.0:11768,29576,12513,13420,38877,17329,16700,41100,8630,15695,8833,15659,9128,10582,8941,10831,11030,7342,8904,9774,10867,9213
18.5:11983,30177,12746,13681,39566,17597,16999,42083,8788,15938,8975,15978,9274,10752,9084,10996,11254,7476,9067,9952,11041,9381
19.0:12197,30778,12978,13943,40255,17865,17298,43066,8945,16181,9116,16296,9420,10921,9227,11160,11479,7609,9229,10130,11216,9548
19.5:12412,31379,13211,14204,40944,18133,17598,44050,9102,16423,9258,16614,9567,11091,9371,11324,11703,7743,9391,10308,11390,9716
20.0:12626,31980,13444,14465,41633,18401,17897,45033,9259,16666,9400,16932,9713,11261,9514,11488,11927,7877,9553,10486,11564,9884
20.5:12841,32581,13676,14727,42322,18669,18197,46016,9417,16908,9541,17251,9860,11430,9658,11653,12151,8011,9716,10664,11739,10052
21.0:12843,32569,16840,17904,42324,20409,18191,46013,9420,17725,12781,17245,12226,12226,11500,14954,27753,8011,9717,10667,11739,10053
21.5:13173,33401,17266,18353,43399,20928,18650,47295,9662,18176,13111,17686,12542,12542,11798,15332,28462,8216,9967,10940,12042,10311
22.0:13502,34234,17692,18801,44475,21447,19108,48577,9904,18626,13442,18127,12858,12858,12095,15709,29171,8422,10216,11214,12346,10569
22.5:13832,35066,18118,19250,45550,21966,19567,49859,10145,19077,13772,18568,13174,13174,12392,16087,29881,8627,10465,11488,12649,10827
23.0:14161,35899,18544,19699,46625,22485,20026,51141,10387,19528,14102,19008,13490,13490,12689,16465,30590,8833,10715,11761,12952,11085
23.5:14491,36731,18971,20148,47700,23004,20484,52422,10629,19979,14433,19449,13806,13806,12986,16843,31299,9038,10964,12035,13256,11343
24.0:14820,37564,19397,20596,48775,23523,20943,53704,10870,20429,14763,19890,14122,14122,13284,17220,32009,9244,11213,12309,13559,11601
24.5:15150,38396,19823,21045,49851,24043,21401,54986,11112,20880,15093,20331,14438,14438,13581,17598,32718,9450,11463,12582,13862,11859
25.0:15479,39229,20249,21494,50926,24562,21860,56268,11354,21331,15424,20772,14754,14754,13878,17976,33428,9655,11712,12856,14166,12116
25.5:15809,40061,20676,21943,52001,25081,22319,57550,11595,21782,15754,21212,15070,15070,14175,18353,34137,9861,11961,13130,14469,12374
26.0:16138,40893,21102,22391,53076,25600,22777,58831,11837,22233,16084,21653,15386,15386,14472,18731,34846,10066,12211,13403,14773,12632
26.5:16468,41726,21528,22840,54151,26119,23236,60113,12079,22683,16414,22094,15702,15702,14770,19109,35556,10272,12460,13677,15076,12890
27.0:16797,42558,21954,23289,55227,26638,23694,61395,12321,23134,16745,22535,16018,16018,15067,19486,36265,10477,12709,13951,15379,13148
27.5:17127,43391,22380,23738,56302,27157,24153,62677,12562,23585,17075,22975,16334,16334,15364,19864,36974,10683,12959,14224,15683,13406
28.0:17456,44223,22807,24187,57377,27676,24612,63959,12804,24036,17405,23416,16650,16650,15661,20242,37684,10888,13208,14498,15986,13664
28.5:17786,45056,23233,24635,58452,28195,25070,65240,13046,24487,17736,23857,16966,16966,15959,20619,38393,11094,13457,14772,16289,13922
29.0:18115,45888,23659,25084,59527,28714,25529,66522,13287,24937,18066,24298,17282,17282,16256,20997,39102,11299,13707,15045,16593,14180
29.5:18445,46721,24085,25533,60603,29233,25988,67804,13529,25388,18396,24739,17598,17598,16553,21375,39812,11505,13956,15319,16896,14438
30.0:18774,47553,24511,25982,61678,29752,26446,69086,13771,25839,18727,25179,17914,17914,16850,21752,40521,11710,14205,15593,17200,14696
30.5:19104,48385,24938,26430,62753,30271,26905,70368,14012,26290,19057,25620,18230,18230,17147,22130,41230,11916,14455,15866,17503,14954
31.0:19433,49218,25364,26879,63828,30790,27363,71650,14254,26741,19387,26061,18546,18546,17445,22508,41940,12121,14704,16140,17806,15212
31.5:19763,50050,25790,27328,64903,31310,27822,72931,14496,27191,19718,26502,18862,18862,17742,22885,42649,12327,14953,16414,18110,15470
32.0:20092,50883,26216,27777,65978,31829,28281,74213,14737,27642,20048,26942,19178,19178,18039,23263,43358,12532,15202,16687,18413,15727
32.5:20422,51715,26643,28225,67054,32348,28739,75495,14979,28093,20378,27383,19494,19494,18336,23641,44068,12738,15452,16961,18716,15985
""".strip()

FICP_PER_KG_RATE_TEXT = """
33.0-44.0:666,1645,885,916,1202,1151,1073,2273,365,975,738,465,683,716,650,818,1281,424,443,561,672,479
45.0-70.0:491,1449,800,843,1091,1020,911,1912,269,865,559,409,518,543,493,630,1128,313,327,414,509,353
71.0-99.0:488,1436,787,830,1082,1013,868,1802,267,859,513,406,475,498,452,627,1119,311,325,411,467,351
100.0-299.0:441,1422,786,829,1082,1013,868,1645,267,859,446,384,456,445,459,604,1119,288,284,377,431,351
300.0-499.0:439,1340,738,775,974,913,773,1479,266,774,444,362,453,442,456,577,1055,286,282,375,429,349
500.0-999.0:436,1297,722,761,972,908,771,1476,264,769,439,350,448,437,451,574,1021,285,280,373,424,347
1000.0-99999.0:434,1293,719,759,964,895,769,1473,263,759,436,349,445,435,448,568,1018,283,279,370,421,345
""".strip()


def parse_standard_rates() -> dict[float, dict[str, int]]:
    rates: dict[float, dict[str, int]] = {}
    for line in FICP_STANDARD_RATE_TEXT.splitlines():
        weight_text, values_text = line.split(":", 1)
        values = [int(value) for value in values_text.split(",")]
        if len(values) != len(FICP_ZONES):
            raise ValueError(f"Invalid FICP row for {weight_text} kg")
        rates[float(weight_text)] = dict(zip(FICP_ZONES, values))
    return rates


def parse_per_kg_rates() -> list[tuple[float, float, dict[str, int]]]:
    rows: list[tuple[float, float, dict[str, int]]] = []
    for line in FICP_PER_KG_RATE_TEXT.splitlines():
        range_text, values_text = line.split(":", 1)
        lower_text, upper_text = range_text.split("-", 1)
        values = [int(value) for value in values_text.split(",")]
        if len(values) != len(FICP_ZONES):
            raise ValueError(f"Invalid FICP per-kg row for {range_text}")
        rows.append((float(lower_text), float(upper_text), dict(zip(FICP_ZONES, values))))
    return rows


FICP_STANDARD_RATES = parse_standard_rates()
FICP_PER_KG_RATES = parse_per_kg_rates()


@dataclass
class ListingData:
    title: str = ""
    price: str = ""
    image_url: str = ""
    description: str = ""
    details_text: str = ""
    status: str = "not fetched"
    source_url: str = ""


@dataclass
class InferredSourceUrl:
    url: str = ""
    confidence: str = "none"
    evidence: str = ""


@dataclass
class FICPCharge:
    zone: str
    input_weight_kg: float
    billed_weight_kg: float
    shipping_jpy: int
    rate_type: str
    per_kg_rate_jpy: Optional[int] = None


@dataclass
class BookWeightEstimate:
    weight_g: int
    evidence: str


@dataclass
class PackagingEstimate:
    weight_kg: float
    materials: str
    evidence: str


@dataclass
class ExchangeRateEstimate:
    rate: float
    source: str
    date: str
    status: str


@dataclass
class ListingExclusion:
    excluded: bool = False
    reason: str = ""
    evidence: str = ""


@dataclass
class ProcessingConfig:
    url_col: str = ""
    image_col: str = ""
    title_col: str = ""
    price_col: str = ""
    description_col: str = ""
    shipping_col: str = ""
    zone: str = DEFAULT_FICP_ZONE
    book_weight_g: int = DEFAULT_BOOK_WEIGHT_G
    packaging_weight_kg: float = DEFAULT_PACKAGING_WEIGHT_KG
    max_book_count_for_export: int = DEFAULT_MAX_BOOK_COUNT_FOR_EXPORT
    exchange_rate_jpy_per_usd: float = DEFAULT_EXCHANGE_RATE_JPY_PER_USD
    exchange_rate_source: str = "manual/default"
    exchange_rate_date: str = ""
    fuel_surcharge_percent: float = 0.0
    enable_scrape: bool = True
    enable_browser_scrape: bool = True
    enable_reference_lookup: bool = False
    request_delay_seconds: float = 0.5
    package_length_cm: float = 0.0
    package_width_cm: float = 0.0
    package_height_cm: float = 0.0
    dimensional_divisor_cm: int = DEFAULT_DIMENSIONAL_DIVISOR_CM
    enable_ai_enrichment: bool = False
    ai_provider: str = DEFAULT_AI_PROVIDER
    ai_model: str = DEFAULT_GEMINI_MODEL
    ai_api_key: str = ""


@dataclass
class FreeShippingRollupOptions:
    enabled: bool = True
    price_col: str = "StartPrice"
    shipping_profile_col: str = "ShippingProfileName"
    free_shipping_profile_name: str = DEFAULT_FREE_SHIPPING_PROFILE_NAME
    markup_percent: float = DEFAULT_FREE_SHIPPING_MARKUP_PERCENT


@dataclass
class SpecificsInference:
    values: dict[str, str]
    notes: list[str]


@dataclass
class AIEnrichment:
    provider: str = ""
    model: str = ""
    status: str = "disabled"
    book_count: Optional[int] = None
    book_count_evidence: str = ""
    description_notes: list[str] = field(default_factory=list)
    specifics: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


@dataclass
class ReferenceBookCountResult:
    status: str = "not used"
    book_count: Optional[int] = None
    source: str = ""
    confidence: str = "none"
    evidence: str = ""
    query: str = ""


def clean_text(value: object) -> str:
    text = unescape(str(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def truncate_text(value: object, limit: int = 600) -> str:
    text = clean_text(value)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip(" ,.;、。") + "…"


def normalize_key(value: object) -> str:
    return re.sub(r"[\s_:\-\/]+", "", str(value or "").lower())


def ai_model_options_for_provider(provider: str) -> list[tuple[str, str]]:
    if normalize_key(provider) == "openai":
        return OPENAI_MODEL_OPTIONS
    return GEMINI_MODEL_OPTIONS


def default_ai_model_for_provider(provider: str) -> str:
    if normalize_key(provider) == "openai":
        return DEFAULT_OPENAI_MODEL
    return DEFAULT_GEMINI_MODEL


def env_flag_enabled(name: str) -> bool:
    return str(os.getenv(name, "")).strip().lower() in {"1", "true", "yes", "on"}


def is_public_mode() -> bool:
    return env_flag_enabled(PUBLIC_MODE_ENV)


def public_database_url() -> str:
    return str(os.getenv(PUBLIC_DATABASE_URL_ENV, "") or "").strip()


def public_storage_database_url_for_tests() -> str:
    return public_database_url() or f"sqlite:///{PUBLIC_AUTH_DB_FALLBACK_PATH}"


def public_encryption_secret() -> str:
    return str(os.getenv(PUBLIC_KEY_SECRET_ENV, "") or "").strip()


def get_public_fernet(secret: str):
    if Fernet is None:
        raise RuntimeError("cryptography is not installed")
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def normalize_public_username(username: object) -> str:
    return re.sub(r"\s+", "", str(username or "").strip().lower())


def hash_public_password(password: str, *, iterations: int = 260_000) -> str:
    password = str(password or "")
    salt = secrets.token_urlsafe(18)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
    return f"pbkdf2_sha256${iterations}${salt}${base64.b64encode(digest).decode('ascii')}"


def verify_public_password(password: str, stored_hash: str) -> bool:
    try:
        scheme, iterations_text, salt, digest_b64 = str(stored_hash or "").split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        iterations = int(iterations_text)
        expected = base64.b64decode(digest_b64.encode("ascii"))
        actual = hashlib.pbkdf2_hmac("sha256", str(password or "").encode("utf-8"), salt.encode("utf-8"), iterations)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def public_db_backend(database_url: str) -> str:
    lower = str(database_url or "").lower()
    if lower.startswith(("postgres://", "postgresql://")):
        return "postgres"
    return "sqlite"


@contextmanager
def public_db_connection(database_url: Optional[str] = None):
    url = str(database_url or public_storage_database_url_for_tests())
    backend = public_db_backend(url)
    if backend == "postgres":
        try:
            import psycopg
        except ImportError as error:  # pragma: no cover - deployment dependency.
            raise RuntimeError("psycopg is not installed") from error
        conn = psycopg.connect(url)
    else:
        path_text = url.replace("sqlite:///", "", 1) if url.startswith("sqlite:///") else url
        db_path = Path(path_text)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
    try:
        yield conn, backend
        conn.commit()
    finally:
        conn.close()


def public_db_param(backend: str) -> str:
    return "%s" if backend == "postgres" else "?"


def init_public_auth_storage(database_url: Optional[str] = None) -> None:
    with public_db_connection(database_url) as (conn, backend):
        cursor = conn.cursor()
        if backend == "postgres":
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS comic_ficp_users (
                    id SERIAL PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    created_at DOUBLE PRECISION NOT NULL
                )
                """
            )
        else:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS comic_ficp_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS comic_ficp_api_keys (
                user_id INTEGER NOT NULL,
                provider TEXT NOT NULL,
                encrypted_value TEXT NOT NULL,
                updated_at DOUBLE PRECISION NOT NULL,
                PRIMARY KEY (user_id, provider)
            )
            """
        )


def public_auth_config_status() -> tuple[bool, str]:
    if not is_public_mode():
        return True, ""
    if not public_database_url():
        return False, f"{PUBLIC_DATABASE_URL_ENV} が未設定です。"
    if not public_encryption_secret():
        return False, f"{PUBLIC_KEY_SECRET_ENV} が未設定です。"
    if Fernet is None:
        return False, "cryptography がインストールされていません。"
    try:
        init_public_auth_storage(public_database_url())
    except Exception as error:
        return False, f"公開版DBの初期化に失敗しました: {redact_sensitive_text(error)}"
    return True, ""


def create_public_user(username: str, password: str, database_url: Optional[str] = None) -> tuple[bool, str]:
    normalized = normalize_public_username(username)
    if len(normalized) < 3:
        return False, "ユーザー名は3文字以上で入力してください。"
    if len(str(password or "")) < 8:
        return False, "パスワードは8文字以上で入力してください。"
    init_public_auth_storage(database_url)
    with public_db_connection(database_url) as (conn, backend):
        cursor = conn.cursor()
        param = public_db_param(backend)
        try:
            cursor.execute(
                f"INSERT INTO comic_ficp_users (username, password_hash, created_at) VALUES ({param}, {param}, {param})",
                (normalized, hash_public_password(password), time.time()),
            )
            return True, "アカウントを作成しました。"
        except Exception as error:
            if "unique" in str(error).lower() or "duplicate" in str(error).lower():
                return False, "このユーザー名はすでに使われています。"
            return False, f"アカウント作成に失敗しました: {redact_sensitive_text(error)}"


def authenticate_public_user(username: str, password: str, database_url: Optional[str] = None) -> tuple[bool, dict[str, str], str]:
    normalized = normalize_public_username(username)
    init_public_auth_storage(database_url)
    with public_db_connection(database_url) as (conn, backend):
        cursor = conn.cursor()
        param = public_db_param(backend)
        cursor.execute(
            f"SELECT id, username, password_hash FROM comic_ficp_users WHERE username = {param}",
            (normalized,),
        )
        row = cursor.fetchone()
    if not row:
        return False, {}, "ユーザー名またはパスワードが違います。"
    user_id, stored_username, password_hash = row[0], row[1], row[2]
    if not verify_public_password(password, str(password_hash)):
        return False, {}, "ユーザー名またはパスワードが違います。"
    return True, {"id": str(user_id), "username": str(stored_username)}, "ログインしました。"


def encrypt_public_api_key(api_key: str, secret: Optional[str] = None) -> str:
    fernet = get_public_fernet(secret or public_encryption_secret())
    return fernet.encrypt(str(api_key or "").encode("utf-8")).decode("ascii")


def decrypt_public_api_key(encrypted_value: str, secret: Optional[str] = None) -> str:
    fernet = get_public_fernet(secret or public_encryption_secret())
    return fernet.decrypt(str(encrypted_value or "").encode("ascii")).decode("utf-8")


def public_saved_api_key_exists(user_id: object, provider: str, database_url: Optional[str] = None) -> bool:
    provider_key = normalize_key(provider)
    with public_db_connection(database_url) as (conn, backend):
        cursor = conn.cursor()
        param = public_db_param(backend)
        cursor.execute(
            f"SELECT 1 FROM comic_ficp_api_keys WHERE user_id = {param} AND provider = {param}",
            (int(user_id), provider_key),
        )
        return cursor.fetchone() is not None


def load_public_saved_api_key(user_id: object, provider: str, database_url: Optional[str] = None, secret: Optional[str] = None) -> str:
    provider_key = normalize_key(provider)
    with public_db_connection(database_url) as (conn, backend):
        cursor = conn.cursor()
        param = public_db_param(backend)
        cursor.execute(
            f"SELECT encrypted_value FROM comic_ficp_api_keys WHERE user_id = {param} AND provider = {param}",
            (int(user_id), provider_key),
        )
        row = cursor.fetchone()
    if not row:
        return ""
    try:
        return decrypt_public_api_key(str(row[0]), secret)
    except Exception:
        return ""


def save_public_api_key(
    user_id: object,
    provider: str,
    api_key: str,
    database_url: Optional[str] = None,
    secret: Optional[str] = None,
) -> tuple[bool, str]:
    api_key = str(api_key or "").strip()
    if not api_key:
        return False, "保存するAPIキーが入力されていません。"
    provider_key = normalize_key(provider)
    try:
        encrypted_value = encrypt_public_api_key(api_key, secret)
        with public_db_connection(database_url) as (conn, backend):
            cursor = conn.cursor()
            param = public_db_param(backend)
            if backend == "postgres":
                cursor.execute(
                    """
                    INSERT INTO comic_ficp_api_keys (user_id, provider, encrypted_value, updated_at)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (user_id, provider)
                    DO UPDATE SET encrypted_value = EXCLUDED.encrypted_value, updated_at = EXCLUDED.updated_at
                    """,
                    (int(user_id), provider_key, encrypted_value, time.time()),
                )
            else:
                cursor.execute(
                    f"""
                    INSERT OR REPLACE INTO comic_ficp_api_keys (user_id, provider, encrypted_value, updated_at)
                    VALUES ({param}, {param}, {param}, {param})
                    """,
                    (int(user_id), provider_key, encrypted_value, time.time()),
                )
        return True, "APIキーを暗号化してサーバーに保存しました。"
    except Exception as error:
        return False, f"APIキーの保存に失敗しました: {redact_sensitive_text(error)}"


def delete_public_saved_api_key(user_id: object, provider: str, database_url: Optional[str] = None) -> tuple[bool, str]:
    provider_key = normalize_key(provider)
    with public_db_connection(database_url) as (conn, backend):
        cursor = conn.cursor()
        param = public_db_param(backend)
        cursor.execute(
            f"DELETE FROM comic_ficp_api_keys WHERE user_id = {param} AND provider = {param}",
            (int(user_id), provider_key),
        )
        deleted = int(getattr(cursor, "rowcount", 0) or 0)
    if deleted:
        return True, "保存済みAPIキーを削除しました。"
    return False, "削除する保存済みAPIキーはありません。"


def current_public_user(st) -> Optional[dict[str, str]]:
    user = st.session_state.get(PUBLIC_SESSION_USER_KEY)
    if isinstance(user, dict) and user.get("id") and user.get("username"):
        return {"id": str(user["id"]), "username": str(user["username"])}
    return None


def clear_public_session_work_data(st) -> None:
    for key in list(st.session_state.keys()):
        key_text = str(key)
        if key_text.startswith("comic_ficp_") or key_text.startswith("usd_jpy_"):
            st.session_state.pop(key, None)


def render_public_login_gate(st) -> bool:
    if not is_public_mode():
        return True
    ok, message = public_auth_config_status()
    if not ok:
        st.error(message)
        st.stop()
        return False
    user = current_public_user(st)
    if user:
        with st.sidebar:
            st.caption(f"ログイン中: {user['username']}")
            if st.button("ログアウト", use_container_width=True):
                st.session_state.pop(PUBLIC_SESSION_USER_KEY, None)
                clear_public_session_work_data(st)
                st.rerun()
        return True

    st.markdown("### ログイン")
    st.caption("公開版では、CSVと処理結果は画面セッション内だけで扱います。AI APIキーだけ、ユーザー別に暗号化保存できます。")
    tab_login, tab_signup = st.tabs(["ログイン", "新規登録"])
    with tab_login:
        login_username = st.text_input("ユーザー名", key="public_login_username")
        login_password = st.text_input("パスワード", type="password", key="public_login_password")
        if st.button("ログインする", type="primary", use_container_width=True):
            authed, user_data, auth_message = authenticate_public_user(login_username, login_password, public_database_url())
            if authed:
                clear_public_session_work_data(st)
                st.session_state[PUBLIC_SESSION_USER_KEY] = user_data
                st.success(auth_message)
                st.rerun()
            else:
                st.warning(auth_message)
    with tab_signup:
        signup_username = st.text_input("ユーザー名", key="public_signup_username")
        signup_password = st.text_input("パスワード（8文字以上）", type="password", key="public_signup_password")
        signup_password_confirm = st.text_input("パスワード確認", type="password", key="public_signup_password_confirm")
        if st.button("アカウントを作成", use_container_width=True):
            if signup_password != signup_password_confirm:
                st.warning("確認用パスワードが一致しません。")
            else:
                created, create_message = create_public_user(signup_username, signup_password, public_database_url())
                if created:
                    authed, user_data, _ = authenticate_public_user(signup_username, signup_password, public_database_url())
                    if authed:
                        clear_public_session_work_data(st)
                        st.session_state[PUBLIC_SESSION_USER_KEY] = user_data
                        st.success(create_message)
                        st.rerun()
                    else:
                        st.success(create_message + " ログインしてください。")
                else:
                    st.warning(create_message)
    st.stop()
    return False


class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def api_key_storage_available() -> bool:
    if is_public_mode():
        return False
    return os.name == "nt"


def _make_data_blob(data: bytes) -> tuple[DATA_BLOB, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data)
    blob = DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    return blob, buffer


def _protect_secret_for_current_user(secret: str) -> str:
    if not api_key_storage_available():
        raise RuntimeError("API key storage is available only on Windows.")
    in_blob, in_buffer = _make_data_blob(secret.encode("utf-8"))
    out_blob = DATA_BLOB()
    result = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        0x01,
        ctypes.byref(out_blob),
    )
    # Keep the input buffer alive until CryptProtectData returns.
    _ = in_buffer
    if not result:
        raise ctypes.WinError()
    try:
        encrypted = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        return base64.b64encode(encrypted).decode("ascii")
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)


def _unprotect_secret_for_current_user(encrypted_base64: str) -> str:
    if not api_key_storage_available():
        raise RuntimeError("API key storage is available only on Windows.")
    encrypted = base64.b64decode(encrypted_base64.encode("ascii"))
    in_blob, in_buffer = _make_data_blob(encrypted)
    out_blob = DATA_BLOB()
    result = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        0x01,
        ctypes.byref(out_blob),
    )
    _ = in_buffer
    if not result:
        raise ctypes.WinError()
    try:
        decrypted = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        return decrypted.decode("utf-8")
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)


def _load_api_key_store() -> dict:
    if not API_KEY_STORE_PATH.exists():
        return {"version": 1, "keys": {}}
    try:
        data = json.loads(API_KEY_STORE_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"version": 1, "keys": {}}
        data.setdefault("version", 1)
        data.setdefault("keys", {})
        return data
    except Exception:
        return {"version": 1, "keys": {}}


def saved_api_key_exists(provider: str) -> bool:
    provider_key = normalize_key(provider)
    data = _load_api_key_store()
    return bool(data.get("keys", {}).get(provider_key, {}).get("value"))


def load_saved_api_key(provider: str) -> str:
    provider_key = normalize_key(provider)
    data = _load_api_key_store()
    entry = data.get("keys", {}).get(provider_key, {})
    if entry.get("scheme") != "windows-dpapi" or not entry.get("value"):
        return ""
    try:
        return _unprotect_secret_for_current_user(str(entry["value"]))
    except Exception:
        return ""


def save_api_key(provider: str, api_key: str) -> tuple[bool, str]:
    if not api_key_storage_available():
        return False, "APIキー保存はWindows環境でのみ利用できます。"
    api_key = str(api_key or "").strip()
    if not api_key:
        return False, "保存するAPIキーが入力されていません。"
    provider_key = normalize_key(provider)
    try:
        encrypted = _protect_secret_for_current_user(api_key)
        data = _load_api_key_store()
        data.setdefault("keys", {})
        data["keys"][provider_key] = {
            "scheme": "windows-dpapi",
            "value": encrypted,
        }
        API_KEY_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        API_KEY_STORE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return True, "APIキーをこのWindowsユーザー用に保存しました。"
    except Exception as exc:
        return False, f"APIキーの保存に失敗しました: {exc}"


def delete_saved_api_key(provider: str) -> tuple[bool, str]:
    provider_key = normalize_key(provider)
    data = _load_api_key_store()
    keys = data.setdefault("keys", {})
    if provider_key in keys:
        del keys[provider_key]
        API_KEY_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        API_KEY_STORE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return True, "保存済みAPIキーを削除しました。"
    return False, "削除する保存済みAPIキーはありません。"


def is_specific_column(column: object) -> bool:
    return str(column or "").strip().lower().startswith("c:")


def specific_label(column: str) -> str:
    if column in SPECIFIC_DISPLAY_LABELS:
        return SPECIFIC_DISPLAY_LABELS[column]
    return re.sub(r"\s+", " ", str(column or "").replace("C:", "", 1)).strip() or str(column)


def get_specific_columns(columns: Iterable[object], include_defaults: bool = True) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for column in columns:
        name = str(column)
        if is_specific_column(name) and name not in seen:
            result.append(name)
            seen.add(name)
    if include_defaults:
        for column in DEFAULT_SPECIFIC_COLUMNS:
            if column not in seen:
                result.append(column)
                seen.add(column)
    return result


def normalized_specific_name(column: object) -> str:
    text = str(column or "").strip()
    if text.lower().startswith("c:"):
        text = text[2:]
    return normalize_key(text)


def contains_japanese_text(value: object) -> bool:
    return bool(re.search(r"[ぁ-んァ-ン一-龥]", str(value or "")))


def is_english_specific_value(value: object) -> bool:
    text = clean_text(value)
    return bool(text) and not contains_japanese_text(text) and bool(re.search(r"[A-Za-z]", text))


def is_blank(value: object) -> bool:
    text = str(value or "").strip()
    return text == "" or text.lower() in {"na", "n/a", "none", "null", "nan", "-", "--"}


def is_replaceable_specific_value(column: object, value: object) -> bool:
    if is_blank(value):
        return True
    key = normalized_specific_name(column)
    text = normalize_key(value)
    if key == "brand" and text in {"nobrand", "unbranded"}:
        return True
    if key in {"isbn", "isbn10", "isbn13"} and text in {"doesnotapply", "n/a", "na"}:
        return True
    return False


def first_nonblank(*values: object) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def parse_image_urls(value: object) -> list[str]:
    source = str(value or "")
    return [
        part.strip()
        for part in re.split(r"[|,;\s]+", source)
        if re.match(r"^https?://", part.strip(), flags=re.I)
    ]


def contains_likely_image_url(value: object) -> bool:
    return any(is_likely_image_url(url) for url in parse_image_urls(value))


def build_preview_image_urls(row: pd.Series, image_col: str) -> list[str]:
    candidates = [
        get_row_value(row, "Main Image URL"),
        *parse_image_urls(get_row_value(row, image_col)),
        *parse_image_urls(get_row_value(row, "Source Image URLs")),
    ]
    result: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        url = str(candidate or "").strip()
        if not is_likely_image_url(url):
            continue
        key = url.split("?", 1)[0].lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(url)
    return result


def build_table_image_url(row: pd.Series, image_col: str) -> str:
    urls = build_preview_image_urls(row, image_col)
    return urls[0] if urls else ""


def collect_export_pic_urls(row: pd.Series, max_images: int = 24) -> list[str]:
    candidates = [
        get_row_value(row, "Main Image URL"),
        *parse_image_urls(get_row_value(row, "PicURL")),
        *parse_image_urls(get_row_value(row, "Source Image URLs")),
    ]
    result: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        url = str(candidate or "").strip()
        if not is_likely_image_url(url):
            continue
        key = url.split("?", 1)[0].lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(url)
        if len(result) >= max_images:
            break
    return result


def is_likely_image_url(url: object) -> bool:
    text = unquote(str(url or "").strip())
    if not text:
        return False
    lower_text = text.lower()
    path = urlparse(text).path.lower()
    return bool(
        re.search(r"\.(?:jpg|jpeg|png|webp|gif)(?:$|[?#])", text, flags=re.I)
        or "mercdn.net" in lower_text
        or "/photos/" in path
        or "/item/detail/" in path
    )


def is_likely_listing_url(url: object) -> bool:
    text = str(url or "").strip()
    if not re.match(r"^https?://", text, flags=re.I):
        return False
    return not is_likely_image_url(text)


def is_mercari_listing_url(url: object) -> bool:
    text = str(url or "").strip().lower()
    return bool(re.match(r"^https?://(?:jp\.)?mercari\.com/(?:item|en/item)/m\d+", text))


def infer_mercari_url_from_image_url(raw_url: object) -> InferredSourceUrl:
    decoded_url = unquote(str(raw_url or "").strip())
    if not decoded_url:
        return InferredSourceUrl(evidence="No image URL was available")

    is_mercari_image = bool(re.search(r"mercdn|mercari", decoded_url, flags=re.I))
    match = re.search(r"(?:^|[\/_-])(m\d{8,})(?:[_./?&=-]|$)", decoded_url, flags=re.I)
    if is_mercari_image and match:
        item_id = match.group(1)
        return InferredSourceUrl(
            url=f"https://jp.mercari.com/item/{item_id}",
            confidence="high",
            evidence=f"Mercari item id {item_id} found in image URL",
        )
    if is_mercari_image:
        return InferredSourceUrl(
            confidence="none",
            evidence="Mercari image URL found, but no item id was present",
        )
    return InferredSourceUrl(
        confidence="none",
        evidence="Image URL is not a Mercari or mercdn URL",
    )


def infer_mercari_url_from_image_urls(image_urls: Iterable[str]) -> InferredSourceUrl:
    fallback_evidence = ""
    for image_url in image_urls:
        inferred = infer_mercari_url_from_image_url(image_url)
        if inferred.url:
            return inferred
        fallback_evidence = fallback_evidence or inferred.evidence
    return InferredSourceUrl(
        confidence="none",
        evidence=fallback_evidence or "No image URL was available",
    )


def resolve_source_url(provided_url: object, image_urls: Iterable[str]) -> tuple[str, InferredSourceUrl, str, str]:
    provided_text = str(provided_url or "").strip()
    image_candidates: list[str] = []
    if provided_text and is_likely_image_url(provided_text):
        image_candidates.append(provided_text)
    image_candidates.extend(image_urls)

    inferred = infer_mercari_url_from_image_urls(image_candidates)
    if provided_text and is_likely_listing_url(provided_text):
        return provided_text, inferred, "provided", "Existing product URL column was used"
    if inferred.url:
        evidence = inferred.evidence
        if provided_text and is_likely_image_url(provided_text):
            evidence = f"Product URL column contained an image URL; {evidence}"
        return inferred.url, inferred, inferred.confidence, evidence
    if provided_text:
        return (
            provided_text,
            inferred,
            "provided",
            "Existing URL could not be identified as an image or product page; used as-is",
        )
    return "", inferred, inferred.confidence, inferred.evidence


def guess_column(headers: Iterable[str], candidates: Iterable[str]) -> str:
    normalized_candidates = [normalize_key(candidate) for candidate in candidates]
    for header in headers:
        key = normalize_key(header)
        if any(candidate in key for candidate in normalized_candidates):
            return header
    return ""


def guess_shipping_cost_column(headers: Iterable[str]) -> str:
    cost_candidates = [
        "shipping cost",
        "shippingcost",
        "shipping service cost",
        "shippingservicecost",
        "postage cost",
        "postagecost",
        "送料額",
        "送料usd",
    ]
    normalized_candidates = [normalize_key(candidate) for candidate in cost_candidates]
    for header in headers:
        key = normalize_key(header)
        if any(blocked in key for blocked in ("profile", "policy", "name", "profilename")):
            continue
        if any(candidate in key for candidate in normalized_candidates):
            return header
    return ""


def guess_shipping_profile_column(headers: Iterable[str]) -> str:
    return guess_column(headers, ["ShippingProfileName", "shipping profile name", "shipping policy", "配送ポリシー"])


def guess_columns(headers: Iterable[str]) -> dict[str, str]:
    headers = list(headers)
    return {
        "url_col": guess_column(
            headers,
            ["商品URL", "商品ページ", "source url", "item url", "listing url", "url", "link"],
        ),
        "image_col": guess_column(
            headers,
            ["picurl", "pictureurl", "picture", "imageurl", "image", "photo", "画像", "写真"],
        ),
        "title_col": guess_column(
            headers,
            ["title", "item title", "name", "商品名", "タイトル", "品名"],
        ),
        "price_col": guess_column(headers, ["price", "start price", "buy it now", "価格", "値段"]),
        "description_col": guess_column(headers, ["description", "desc", "商品説明", "説明"]),
        "shipping_col": guess_shipping_cost_column(headers),
        "shipping_profile_col": guess_shipping_profile_column(headers),
    }


def read_csv_bytes(raw: bytes) -> tuple[pd.DataFrame, str]:
    last_error: Optional[Exception] = None
    for encoding in ("utf-8-sig", "cp932", "shift_jis"):
        try:
            frame = pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False, encoding=encoding)
            return frame.fillna(""), encoding
        except Exception as error:  # pragma: no cover - exercised through UI.
            last_error = error
    raise ValueError(f"CSVを読み込めませんでした: {last_error}")


def dataframe_to_csv_bytes(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")


def ceil_money(value: float) -> float:
    return math.ceil((float(value) - 1e-9) * 100) / 100


def calculate_free_shipping_rollup(
    start_price: object,
    shipping_usd: object,
    markup_percent: float,
) -> tuple[Optional[dict[str, float]], str]:
    price = parse_float_text(start_price)
    shipping = parse_float_text(shipping_usd)
    if price is None:
        return None, "skipped: StartPrice is not numeric"
    if shipping is None or shipping <= 0:
        return None, "skipped: FICP Shipping USD is missing"
    markup_usd = ceil_money(shipping * max(markup_percent, 0.0) / 100)
    transfer_usd = ceil_money(shipping + markup_usd)
    adjusted_price = ceil_money(price + transfer_usd)
    return (
        {
            "original_price": price,
            "ficp_shipping_usd": shipping,
            "markup_usd": markup_usd,
            "transfer_usd": transfer_usd,
            "adjusted_price": adjusted_price,
        },
        "applied",
    )


def apply_free_shipping_rollup(
    frame: pd.DataFrame,
    options: FreeShippingRollupOptions,
) -> pd.DataFrame:
    result = frame.copy()
    audit_columns = [
        "Original StartPrice",
        "Shipping Transfer USD",
        "Shipping Transfer Markup Percent",
        "Shipping Transfer Markup USD",
        "Adjusted StartPrice",
        "Original ShippingProfileName",
        "Applied ShippingProfileName",
        "Free Shipping Rollup Status",
    ]
    for column in audit_columns:
        if column not in result.columns:
            result[column] = ""

    price_col = options.price_col or "StartPrice"
    profile_col = options.shipping_profile_col or "ShippingProfileName"
    if profile_col not in result.columns:
        result[profile_col] = ""

    policy_name = options.free_shipping_profile_name.strip() or DEFAULT_FREE_SHIPPING_PROFILE_NAME
    for index, row in result.iterrows():
        original_price = get_row_value(row, price_col)
        original_profile = get_row_value(row, profile_col)
        result.at[index, "Original StartPrice"] = original_price
        result.at[index, "Original ShippingProfileName"] = original_profile
        result.at[index, "Shipping Transfer Markup Percent"] = f"{options.markup_percent:.2f}"

        if not price_col or price_col not in result.columns:
            result.at[index, "Free Shipping Rollup Status"] = "skipped: StartPrice column is not selected"
            continue

        calculation, status = calculate_free_shipping_rollup(
            start_price=original_price,
            shipping_usd=get_row_value(row, "FICP Shipping USD"),
            markup_percent=options.markup_percent,
        )
        result.at[index, "Free Shipping Rollup Status"] = status
        if not calculation:
            continue

        result.at[index, "Shipping Transfer USD"] = f"{calculation['transfer_usd']:.2f}"
        result.at[index, "Shipping Transfer Markup USD"] = f"{calculation['markup_usd']:.2f}"
        result.at[index, "Adjusted StartPrice"] = f"{calculation['adjusted_price']:.2f}"
        result.at[index, "Applied ShippingProfileName"] = policy_name
        result.at[index, price_col] = f"{calculation['adjusted_price']:.2f}"
        result.at[index, profile_col] = policy_name

    return result


DEFAULT_EXPORT_CONDITION_ID = "4000"
DEFAULT_EXPORT_CONDITION_NAME = "Very Good"
DEFAULT_EXPORT_UNIT_TYPE = "Book"


def apply_export_condition_id_policy(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    if "ConditionID" not in result.columns:
        result["ConditionID"] = ""

    audit_columns = [
        "Original ConditionID",
        "Applied ConditionID",
        "ConditionID Fix Status",
    ]
    for column in audit_columns:
        if column not in result.columns:
            result[column] = ""

    for index, row in result.iterrows():
        condition_id = str(get_row_value(row, "ConditionID")).strip()
        result.at[index, "Original ConditionID"] = condition_id

        result.at[index, "ConditionID"] = DEFAULT_EXPORT_CONDITION_ID
        result.at[index, "Applied ConditionID"] = DEFAULT_EXPORT_CONDITION_ID
        if condition_id == DEFAULT_EXPORT_CONDITION_ID:
            result.at[index, "ConditionID Fix Status"] = f"kept: {DEFAULT_EXPORT_CONDITION_NAME}"
        else:
            result.at[index, "ConditionID Fix Status"] = (
                f"fixed: set ConditionID to {DEFAULT_EXPORT_CONDITION_ID} "
                f"({DEFAULT_EXPORT_CONDITION_NAME}) per export policy"
            )

    return result


def apply_export_picurl_policy(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    if "PicURL" not in result.columns:
        return result

    audit_columns = [
        "Original PicURL",
        "Applied PicURL Image Count",
        "PicURL Export Status",
    ]
    for column in audit_columns:
        if column not in result.columns:
            result[column] = ""

    for index, row in result.iterrows():
        original_picurl = get_row_value(row, "PicURL")
        image_urls = collect_export_pic_urls(row)
        result.at[index, "Original PicURL"] = original_picurl
        if image_urls:
            result.at[index, "PicURL"] = "|".join(image_urls)
            result.at[index, "Applied PicURL Image Count"] = str(len(image_urls))
            if len(image_urls) == 1:
                result.at[index, "PicURL Export Status"] = "kept: one image available"
            else:
                result.at[index, "PicURL Export Status"] = f"applied: {len(image_urls)} images"
        else:
            result.at[index, "Applied PicURL Image Count"] = "0"
            result.at[index, "PicURL Export Status"] = "skipped: no image URL available"

    return result


def apply_export_unit_type_policy(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    if "C:Unit Type" not in result.columns:
        result["C:Unit Type"] = ""
    if "C:Unit Quantity" not in result.columns:
        result["C:Unit Quantity"] = ""

    audit_columns = [
        "Original Unit Type",
        "Applied Unit Type",
        "Unit Type Fix Status",
    ]
    for column in audit_columns:
        if column not in result.columns:
            result[column] = ""

    for index, row in result.iterrows():
        original_unit_type = get_row_value(row, "C:Unit Type")
        unit_quantity = get_row_value(row, "C:Unit Quantity")
        detected_count = get_row_value(row, "Detected Book Count")

        result.at[index, "Original Unit Type"] = original_unit_type
        if is_blank(unit_quantity) and not is_blank(detected_count):
            result.at[index, "C:Unit Quantity"] = str(detected_count).strip()
            unit_quantity = str(detected_count).strip()

        if is_blank(unit_quantity):
            result.at[index, "Applied Unit Type"] = original_unit_type
            result.at[index, "Unit Type Fix Status"] = "skipped: unit quantity is missing"
            continue

        if is_replaceable_specific_value("C:Unit Type", original_unit_type):
            result.at[index, "C:Unit Type"] = DEFAULT_EXPORT_UNIT_TYPE
            result.at[index, "Applied Unit Type"] = DEFAULT_EXPORT_UNIT_TYPE
            result.at[index, "Unit Type Fix Status"] = "fixed: set unit type to Book"
        else:
            result.at[index, "Applied Unit Type"] = original_unit_type
            result.at[index, "Unit Type Fix Status"] = "kept"

    return result


def build_export_eligibility_mask(frame: pd.DataFrame) -> pd.Series:
    export_mask = pd.Series(True, index=frame.index)
    if "Listing Eligibility" in frame.columns:
        export_mask &= frame["Listing Eligibility"].astype(str).str.strip().str.lower() != "excluded"
    if "Processing Result" in frame.columns:
        export_mask &= frame["Processing Result"].astype(str).str.strip() != "確認必要"
    if "Needs Review" in frame.columns:
        export_mask &= frame["Needs Review"].astype(str).str.strip().str.lower() != "yes"
    return export_mask


def build_export_dataframe(
    frame: pd.DataFrame,
    free_shipping_rollup: Optional[FreeShippingRollupOptions] = None,
) -> pd.DataFrame:
    export_mask = build_export_eligibility_mask(frame)
    export_frame = frame.loc[export_mask].copy()
    export_frame = apply_export_picurl_policy(export_frame)
    export_frame = apply_export_condition_id_policy(export_frame)
    export_frame = apply_export_unit_type_policy(export_frame)
    if free_shipping_rollup and free_shipping_rollup.enabled:
        export_frame = apply_free_shipping_rollup(export_frame, free_shipping_rollup)
    return export_frame


def summarize_free_shipping_rollup(frame: pd.DataFrame) -> dict[str, str]:
    if "Free Shipping Rollup Status" not in frame.columns:
        return {"applied": "0", "skipped": "0", "average_transfer_usd": "-"}
    statuses = frame["Free Shipping Rollup Status"].astype(str)
    applied_mask = statuses.str.lower().eq("applied")
    transfers = pd.to_numeric(frame.get("Shipping Transfer USD", pd.Series(dtype=str)), errors="coerce")
    average_transfer = transfers[applied_mask].mean()
    return {
        "applied": str(int(applied_mask.sum())),
        "skipped": str(int((statuses.str.strip() != "").sum() - applied_mask.sum())),
        "average_transfer_usd": f"${average_transfer:.2f}" if pd.notna(average_transfer) else "-",
    }


def build_ebay_preflight_table(
    source_frame: pd.DataFrame,
    export_frame: pd.DataFrame,
    title_col: str,
) -> pd.DataFrame:
    specific_columns = get_specific_columns(export_frame.columns, include_defaults=False)
    rows: list[dict[str, str]] = []
    for idx, row in export_frame.iterrows():
        title = first_nonblank(
            get_row_value(row, title_col),
            get_row_value(row, "Title"),
            get_row_value(row, "Source Listing Title"),
            get_row_value(row, "C:Book Title"),
        )
        issues: list[str] = []
        warnings: list[str] = []

        image_count_text = get_row_value(row, "Applied PicURL Image Count")
        image_count_value = parse_float_text(image_count_text)
        image_count = int(image_count_value) if image_count_value is not None else len(collect_export_pic_urls(row))
        if image_count <= 0:
            issues.append("画像URLなし")
        elif image_count == 1:
            warnings.append("画像1枚のみ")

        category = get_row_value(row, "Category")
        condition_id = get_row_value(row, "ConditionID")
        if not category:
            issues.append("Category空欄")
        if condition_id != DEFAULT_EXPORT_CONDITION_ID:
            issues.append(f"ConditionIDが{DEFAULT_EXPORT_CONDITION_ID}ではありません")

        title_length = len(title)
        if not title:
            issues.append("Title空欄")
        elif title_length > 80:
            issues.append(f"Titleが80文字超過({title_length})")
        elif title_length > 75:
            warnings.append(f"Titleが長め({title_length})")

        start_price = get_row_value(row, "StartPrice")
        if parse_float_text(start_price) is None:
            issues.append("StartPriceが数値ではありません")
        if not get_row_value(row, "ShippingProfileName"):
            warnings.append("ShippingProfileName空欄")
        if not get_row_value(row, "Description"):
            warnings.append("Description空欄")

        long_specifics = []
        for column in specific_columns:
            value = get_row_value(row, column)
            if value and len(value) > 65:
                label = column[2:] if column.startswith("C:") else column
                long_specifics.append(f"{label}({len(value)})")
        if long_specifics:
            issues.append("Specifics 65文字超過: " + ", ".join(long_specifics[:4]))

        rollup_status = get_row_value(row, "Free Shipping Rollup Status")
        if rollup_status and rollup_status != "applied":
            warnings.append(f"送料無料転嫁: {rollup_status}")

        status = "OK"
        if issues:
            status = "要修正"
        elif warnings:
            status = "注意"

        rows.append(
            {
                "No": str(idx + 1),
                "Image": build_table_image_url(row, "PicURL"),
                "Status": status,
                "Title": truncate_text(title, 90),
                "Images": str(image_count),
                "Category": category or "-",
                "ConditionID": condition_id or "-",
                "StartPrice": start_price or "-",
                "ShippingProfileName": get_row_value(row, "ShippingProfileName") or "-",
                "Issues": "; ".join(issues) if issues else "-",
                "Warnings": "; ".join(warnings) if warnings else "-",
            }
        )

    excluded_count = 0
    if not source_frame.empty:
        excluded_count = int((~build_export_eligibility_mask(source_frame)).sum())
    if excluded_count:
        rows.append(
            {
                "No": "-",
                "Image": "",
                "Status": "除外済み",
                "Title": f"ダウンロードCSVから除外される商品: {excluded_count}件",
                "Images": "-",
                "Category": "-",
                "ConditionID": "-",
                "StartPrice": "-",
                "ShippingProfileName": "-",
                "Issues": "-",
                "Warnings": "除外候補タブで理由を確認できます",
            }
        )
    return pd.DataFrame(rows)


def redact_sensitive_text(value: object) -> str:
    """画面やCSVに出す診断文からAPIキーなどの秘密情報を取り除く。"""
    text = str(value or "")
    if not text:
        return ""
    text = re.sub(r"([?&]key=)[^&\s]+", r"\1[redacted]", text, flags=re.I)
    text = re.sub(r"(key=)[^&\s]+", r"\1[redacted]", text, flags=re.I)
    text = re.sub(r"([?&](?:api_key|token|password|secret)=)[^&\s]+", r"\1[redacted]", text, flags=re.I)
    text = re.sub(r"(postgres(?:ql)?://[^:\s/@]+:)[^@\s]+@", r"\1[redacted]@", text, flags=re.I)
    text = re.sub(r"AIza[0-9A-Za-z_-]{20,}", "[redacted-api-key]", text)
    text = re.sub(r"sk-[A-Za-z0-9_-]{20,}", "[redacted-api-key]", text)
    text = re.sub(r"(Bearer\s+)[A-Za-z0-9._~+/=-]+", r"\1[redacted]", text, flags=re.I)
    return text


def format_ai_error_status(provider: str, error: Exception) -> str:
    provider_label = "Gemini" if normalize_key(provider) == "gemini" else "OpenAI"
    response = getattr(error, "response", None)
    status_code = getattr(response, "status_code", None)
    reason = str(getattr(response, "reason", "") or "").strip()
    if status_code:
        if int(status_code) == 503:
            return f"error: {provider_label} API is temporarily unavailable (HTTP 503). Retry later or switch provider/model."
        if int(status_code) == 429:
            return f"error: {provider_label} API rate limit or quota reached (HTTP 429). Retry later or change model/provider."
        if int(status_code) in {401, 403}:
            return f"error: {provider_label} API authentication failed (HTTP {status_code}). Check the saved API key."
        suffix = f" {reason}" if reason else ""
        return f"error: {provider_label} API request failed (HTTP {status_code}{suffix})."
    return f"error: {redact_sensitive_text(error)}"


def row_is_processed(row: pd.Series) -> bool:
    return bool(
        get_row_value(row, "Scrape Status")
        or get_row_value(row, "Detected Book Count")
        or get_row_value(row, "FICP Shipping USD")
        or get_row_value(row, "Specifics Fill Notes")
        or get_row_value(row, "Listing Eligibility")
    )


def diagnose_processed_row(row: pd.Series) -> dict[str, str]:
    """処理後の行から、画面とCSVに残す診断結果を作る。"""
    if not row_is_processed(row):
        return {
            "result": "未処理",
            "severity": "未処理",
            "diagnostics": "まだ処理されていません。",
            "needs_review": "No",
            "review_reason": "",
        }

    status = get_row_value(row, "Scrape Status")
    status_lower = status.lower()
    eligibility = get_row_value(row, "Listing Eligibility")
    eligibility_lower = eligibility.lower()
    book_count = get_row_value(row, "Detected Book Count")
    book_count_status = get_row_value(row, "Book Count Status")
    billable_weight = get_row_value(row, "Billable Weight kg")
    shipping_usd = get_row_value(row, "FICP Shipping USD")
    image_url = get_row_value(row, "Main Image URL")
    ai_status = redact_sensitive_text(get_row_value(row, "AI Enrichment Status"))
    ai_status_lower = ai_status.lower()
    core_pricing_ready = bool(book_count and billable_weight and shipping_usd)

    details: list[str] = []
    review_reasons: list[str] = []

    if eligibility_lower == "excluded":
        reason = get_row_value(row, "Exclusion Reason") or "出品除外"
        evidence = get_row_value(row, "Exclusion Evidence")
        details.append(f"出品除外: {reason}")
        if evidence:
            details.append(f"除外根拠: {evidence}")
        review_reasons.append(reason)
    elif eligibility:
        details.append(f"出品判定: {eligibility}")

    if status:
        details.append(f"商品情報取得: {status}")
    if re.search(r"failed|error|unsupported|missing|no url|not found", status_lower):
        if "browser fetch failed" in status_lower and core_pricing_ready:
            details.append("公開ページのブラウザ取得は失敗しましたが、CSV内情報と取得済み情報で冊数・重量・送料を計算済みです。")
        else:
            review_reasons.append(f"商品情報取得に注意: {status}")

    if book_count:
        evidence = get_row_value(row, "Book Count Evidence")
        details.append(f"冊数: {book_count}冊" + (f" / {evidence}" if evidence else ""))
    else:
        details.append(book_count_status or "冊数判定不能")
        review_reasons.append(book_count_status or "冊数判定不能")
        reference_status = get_row_value(row, "Reference Count Status")
        reference_evidence = get_row_value(row, "Reference Count Evidence")
        if reference_status:
            details.append(f"参照冊数: {reference_status}" + (f" / {reference_evidence}" if reference_evidence else ""))

    if billable_weight:
        source = get_row_value(row, "Billable Weight Source")
        details.append(f"課金重量: {billable_weight}kg" + (f" ({source})" if source else ""))
    else:
        review_reasons.append("重量未計算")

    if shipping_usd:
        shipping_jpy = get_row_value(row, "FICP Shipping JPY")
        details.append(f"送料: ${shipping_usd}" + (f" / JPY {shipping_jpy}" if shipping_jpy else ""))
    else:
        review_reasons.append("送料未計算")

    if not image_url:
        review_reasons.append("画像未取得")

    if ai_status and re.search(r"error|parse error|missing api key", ai_status_lower):
        details.append(f"AI補完は任意処理のため未反映: {ai_status}")
    elif ai_status:
        details.append(f"AI補完: {ai_status}")

    if eligibility_lower == "excluded":
        result = "出品除外"
        severity = "出品除外"
    elif review_reasons:
        result = "確認必要"
        severity = "注意"
    else:
        result = "成功"
        severity = "正常"

    return {
        "result": result,
        "severity": severity,
        "diagnostics": "; ".join(dict.fromkeys(part for part in details if part)),
        "needs_review": "Yes" if review_reasons else "No",
        "review_reason": "; ".join(dict.fromkeys(part for part in review_reasons if part)),
    }


def apply_processing_diagnostics(row: pd.Series) -> pd.Series:
    diagnostics = diagnose_processed_row(row)
    result = diagnostics["result"]
    severity = diagnostics["severity"]
    if result == "確認必要":
        row["Listing Eligibility"] = "Excluded"
        row["Exclusion Reason"] = "確認が必要なため出品除外"
        row["Exclusion Evidence"] = diagnostics["review_reason"]
        result = "出品除外"
        severity = "出品除外"
        diagnostics["diagnostics"] = "; ".join(
            dict.fromkeys(
                part
                for part in [
                    diagnostics["diagnostics"],
                    f"出品除外: 確認必要 ({diagnostics['review_reason']})",
                ]
                if part
            )
        )
    row["Processing Result"] = result
    row["Processing Severity"] = severity
    row["Processing Diagnostics"] = diagnostics["diagnostics"]
    row["Needs Review"] = diagnostics["needs_review"]
    row["Needs Review Reason"] = diagnostics["review_reason"]
    return row


def normalize_count_text(text: object) -> str:
    normalized = str(text or "").translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    normalized = normalized.replace("〜", "-").replace("～", "-").replace("ー", "-")
    normalized = normalized.replace("－", "-").replace("―", "-").replace("–", "-").replace("—", "-")
    return normalized


SAFE_NON_MISSING_CONTEXT = re.compile(
    r"誤発注|発注してしま|間違えて(?:購入|注文)|誤って(?:購入|注文)|重複(?:購入|注文)|"
    r"ダブって|かぶって|一読もしておりません|読んでおりません|未読|新品で購入したばかり|"
    r"問題(?:は)?ない|使用感がない|傷や汚れなし|喫煙者(?:は)?いません",
    flags=re.I,
)

ACCESSORY_ABSENCE_CONTEXT = re.compile(
    r"シュリンク|帯なし|帯無し|帯は(?:付いて|ついて|ありません|ない)|応募券|特典|付録",
    flags=re.I,
)

CORE_MISSING_PATTERNS = [
    re.compile(
        r"(?:なぜか|何故か)?\s*\d{1,3}\s*(?:巻|卷|かん|カン|冊|册|本)\s*(?:だけ|のみ)?\s*(?:が|は)?\s*"
        r"(?:ありません|ない|無し|なし|欠品|欠損|抜け|抜けて|欠け|不足)",
        flags=re.I,
    ),
    re.compile(
        r"\d{1,3}\s*(?:巻|卷|かん|カン|冊|册|本)\s*(?:欠品|欠損|欠け|不足|抜け)",
        flags=re.I,
    ),
    re.compile(
        r"(?:全巻ではありません|全巻(?:セット)?ではない|完品ではありません|完品ではない|"
        r"揃っていません|そろっていません|一部(?:巻|冊)?(?:が)?(?:ありません|ない|欠品|欠損|不足)|"
        r"巻抜け|抜け巻|欠巻|欠本)",
        flags=re.I,
    ),
]

SAFE_COMIC_BOOK_CONTEXT = re.compile(
    r"ジャンプコミックス|jump comics|ヤンマガ\s*KC|ヤンマガKC|KCコミックス|講談社コミックス|"
    r"コミックス|comic books?|単行本|全巻|巻セット|文庫版|完全版|連載作品",
    flags=re.I,
)

GENERIC_BOOKS_CATEGORY_CONTEXT = re.compile(
    r"本\s*[・>＞/／]\s*雑誌\s*[・>＞/／]\s*漫画.*(?:漫画|コミック|全巻セット)",
    flags=re.I,
)

MAGAZINE_HARD_PATTERNS = [
    re.compile(r"\d{4}\s*年\s*\d{1,3}\s*号", flags=re.I),
    re.compile(r"\d{1,2}\s*月号", flags=re.I),
    re.compile(r"\bno\.?\s*\d{1,3}\b", flags=re.I),
    re.compile(r"合併号|特大号|増刊号|magazine\s+issue", flags=re.I),
    re.compile(r"(?:ジャンプ|マガジン|サンデー|ガンガン|ヤングジャンプ|ヤングマガジン).{0,12}本誌", flags=re.I),
]

MAGAZINE_CONTEXT_PATTERNS = [
    re.compile(r"週刊\s*(?:少年)?\s*(?:ジャンプ|マガジン|サンデー|チャンピオン|ヤングジャンプ|ヤングマガジン)", flags=re.I),
    re.compile(r"月刊\s*(?:少年|少女)?\s*(?:ガンガン|マガジン|ジャンプ|サンデー|チャンピオン)", flags=re.I),
    re.compile(r"別冊\s*(?:少年|少女)?\s*(?:マガジン|マーガレット|フレンド|チャンピオン)", flags=re.I),
    re.compile(r"増刊\s*(?:号)?|本誌|雑誌", flags=re.I),
]


def is_core_missing_issue_sentence(sentence: str) -> bool:
    normalized = normalize_count_text(sentence)
    if not normalized:
        return False
    if SAFE_NON_MISSING_CONTEXT.search(normalized):
        return False
    if ACCESSORY_ABSENCE_CONTEXT.search(normalized) and not any(pattern.search(normalized) for pattern in CORE_MISSING_PATTERNS):
        return False
    return any(pattern.search(normalized) for pattern in CORE_MISSING_PATTERNS)


def is_magazine_issue_sentence(sentence: str) -> bool:
    normalized = normalize_count_text(sentence)
    if not normalized:
        return False
    if GENERIC_BOOKS_CATEGORY_CONTEXT.search(normalized):
        return False
    if any(pattern.search(normalized) for pattern in MAGAZINE_HARD_PATTERNS):
        return True
    if not any(pattern.search(normalized) for pattern in MAGAZINE_CONTEXT_PATTERNS):
        return False
    return not SAFE_COMIC_BOOK_CONTEXT.search(normalized)


def detect_unlistable_listing_issue(*texts: object) -> ListingExclusion:
    source = "\n".join(clean_text(text) for text in texts if clean_text(text))
    if not source:
        return ListingExclusion()

    # eBay出品事故を避けるため、巻・冊など商品本体の欠けを示す文だけを出品除外にする。
    # 「誤発注」「一読もしていない」「シュリンクなし」などは欠品ではないため除外しない。
    for sentence in split_detail_sentences(source):
        if is_core_missing_issue_sentence(sentence):
            return ListingExclusion(
                excluded=True,
                reason="商品本体の欠巻・欠品・欠損の可能性があるため出品除外",
                evidence=truncate_text(sentence, 220),
            )
    return ListingExclusion()


def detect_magazine_listing_issue(*texts: object) -> ListingExclusion:
    source = "\n".join(clean_text(text) for text in texts if clean_text(text))
    if not source:
        return ListingExclusion()

    for sentence in split_detail_sentences(source):
        if is_magazine_issue_sentence(sentence):
            return ListingExclusion(
                excluded=True,
                reason="雑誌・本誌商品の可能性があるため出品除外",
                evidence=truncate_text(sentence, 220),
            )
    return ListingExclusion()


def detect_book_count(text: object) -> tuple[Optional[int], str]:
    source = normalize_count_text(text)
    candidates: list[tuple[int, int, str]] = []
    range_candidates: list[tuple[int, int, str, tuple[int, int, str]]] = []
    seen_range_signatures: set[tuple[int, int, str]] = set()
    seen_range_evidences: set[tuple[int, int, str]] = set()
    seen_range_spans: list[tuple[int, int, int, int]] = []

    def add_candidate(score: int, count: int, evidence: str) -> None:
        if 1 <= count <= 300:
            candidates.append((score, count, evidence.strip()))

    def range_context_signature(match: re.Match[str], start: int, end: int) -> tuple[int, int, str]:
        window = source[max(0, match.start() - 60) : min(len(source), match.end() + 40)]
        context = re.sub(
            r"\d{1,3}\s*(?:巻|卷)?\s*(?:-|~|から|to|through)\s*\d{1,3}\s*(?:巻|卷)?",
            " ",
            window,
            flags=re.I,
        )
        context = re.sub(
            r"\b(?:vol(?:ume)?s?\.?|books?|complete|completed|full|all|set|series|lot|bundle)\b|"
            r"全巻|完結|セット|まとめ|巻|卷|冊|册",
            " ",
            context,
            flags=re.I,
        )
        context = re.sub(r"[\s　,，.。;；:：!！?？/／\\|()（）\[\]【】「」『』\"'`]+", "", context)
        return (start, end, context.lower()[:80])

    def add_range_candidate(score: int, start: int, end: int, evidence: str, match: re.Match[str]) -> None:
        if end < start:
            return
        count = end - start + 1
        if not (1 <= count <= 300):
            return
        prefix = source[max(0, match.start() - 16) : match.start()]
        if re.match(r"^\d", evidence.strip()) and re.search(r"(?:vol(?:ume)?s?\.?|books?)\s*$", prefix, flags=re.I):
            return
        span = (match.start(), match.end())
        if any(
            existing_start == start
            and existing_end == end
            and max(span[0], existing_span_start) < min(span[1], existing_span_end)
            for existing_start, existing_end, existing_span_start, existing_span_end in seen_range_spans
        ):
            return
        evidence_key = (start, end, re.sub(r"\s+", "", evidence.lower()))
        if evidence_key in seen_range_evidences:
            return
        signature = range_context_signature(match, start, end)
        if signature in seen_range_signatures:
            return
        seen_range_signatures.add(signature)
        seen_range_evidences.add(evidence_key)
        seen_range_spans.append((start, end, span[0], span[1]))
        candidates.append((score, count, evidence.strip()))
        range_candidates.append((score, count, evidence.strip(), signature))

    def collapse_ranges_for_sum(
        items: list[tuple[int, int, str, tuple[int, int, str]]],
    ) -> list[tuple[int, int, str, tuple[int, int, str]]]:
        best_by_exact_range: dict[tuple[int, int], tuple[int, int, str, tuple[int, int, str]]] = {}
        for item in items:
            score, count, evidence, signature = item
            start, end, _ = signature
            existing = best_by_exact_range.get((start, end))
            if existing is None or (score, len(evidence)) > (existing[0], len(existing[2])):
                best_by_exact_range[(start, end)] = item

        unique_ranges = list(best_by_exact_range.values())
        collapsed: list[tuple[int, int, str, tuple[int, int, str]]] = []
        for item in unique_ranges:
            _, _, _, signature = item
            start, end, _ = signature
            is_inside_larger_range = any(
                other_signature[0] < start and other_signature[1] == end
                for _, _, _, other_signature in unique_ranges
            )
            if not is_inside_larger_range:
                collapsed.append(item)

        return collapsed

    # 例: 1-20巻 / 1-20巻セット / 1巻-20巻
    for pattern in (
        r"(?<!\d)(\d{1,3})\s*(?:-|~|から)\s*(\d{1,3})\s*(?:巻|卷)",
        r"(?<!\d)(\d{1,3})\s*(?:-|~|から)\s*(\d{1,3})\s*(?:全巻|完結|セット)",
        r"(?<!\d)(\d{1,3})\s*(?:巻|卷)\s*(?:-|~|から)\s*(\d{1,3})\s*(?:巻|卷)",
        r"\b(?:vol(?:ume)?s?\.?)\s*(\d{1,3})\s*(?:-|~|to|through)\s*(\d{1,3})\b",
        r"\b(\d{1,3})\s*(?:-|~|to|through)\s*(\d{1,3})\s*(?:vol(?:ume)?s?|books?)\b",
        r"\b(\d{1,3})[ \t]*(?:-|~|to|through)[ \t]*(\d{1,3})[ \t]*(?:complete|completed|full|set|all)\b",
    ):
        for match in re.finditer(pattern, source, flags=re.I):
            start, end = int(match.group(1)), int(match.group(2))
            score = 110 if start == 1 else 95
            add_range_candidate(score, start, end, match.group(0), match)

    # 例: 全5巻 / 完結セット(全5巻) / コミック全23巻
    for pattern in (
        r"(?:全|全巻|完結セット\s*[\(（]?\s*全?)\s*(\d{1,3})\s*(?:巻|卷|冊|册)",
        r"(?:コミック|漫画|マンガ).{0,8}?全\s*(\d{1,3})\s*(?:巻|卷|冊|册)",
    ):
        for match in re.finditer(pattern, source, flags=re.I):
            add_candidate(105, int(match.group(1)), match.group(0))

    # 例: 10冊セット / 23冊まとめ売り
    for pattern in (
        r"(?<!\d)(\d{1,3})\s*(?:冊|册)\s*(?:セット|まとめ|組|入り|分)",
        r"(?<!\d)(\d{1,3})\s*(?:巻|卷)\s*(?:セット|全巻|完結|まとめ)",
        r"(?<!\d)(\d{1,3})\s*(?:book|books|volume|volumes|vols?\.?)\s*(?:set|lot|bundle)",
    ):
        for match in re.finditer(pattern, source, flags=re.I):
            add_candidate(100, int(match.group(1)), match.group(0))

    if not candidates:
        return None, ""

    # 1商品に複数シリーズの全巻範囲が含まれる場合は合算する。
    # 例: 「浦安鉄筋家族1-31全巻 元祖!浦安鉄筋家族1-28全巻」=> 31 + 28 = 59冊。
    strong_ranges = collapse_ranges_for_sum([item for item in range_candidates if item[0] >= 95])
    if len(strong_ranges) >= 2:
        total = sum(item[1] for item in strong_ranges)
        if 1 <= total <= 300:
            evidence = " + ".join(item[2] for item in strong_ranges)
            return total, evidence

    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    _, count, evidence = candidates[0]
    return count, evidence


def has_complete_set_claim(text: object) -> bool:
    source = normalize_count_text(text)
    return bool(
        re.search(
            r"\b(?:complete|completed)\s+(?:manga\s+|comic\s+)?(?:set|series)\b|"
            r"\bfull\s+set\b|\ball\s+volumes\b|\ball\s+vols\b|"
            r"全巻|全巻セット|全巻揃|完結(?:セット)?",
            source,
            flags=re.I,
        )
    )


def detect_book_count_from_reference(text: object) -> tuple[Optional[int], str]:
    """数字がないComplete Set表記だけを、既知シリーズの全巻数で補完する。"""
    source = normalize_count_text(text)
    if not source or not has_complete_set_claim(source):
        return None, ""
    series_title = infer_known_alias(source, SERIES_ALIASES)
    if not series_title:
        return None, ""
    reference = SERIES_REFERENCE_DATA.get(series_title, {})
    raw_count = reference.get("complete_volume_count") or reference.get("volume_count")
    try:
        count = int(raw_count)
    except Exception:
        return None, ""
    if 1 <= count <= 300:
        return count, f"{series_title} complete-series reference: {count} volumes"
    return None, ""


def infer_series_title_for_book_count_reference(title: str, details_text: str, combined_text: str) -> str:
    """全巻系表記だけの商品から、無料参照検索に使う作品名を保守的に作る。"""
    known_series = infer_known_alias(f"{title}\n{details_text}\n{combined_text}", SERIES_ALIASES)
    if known_series:
        return known_series
    source = clean_text(first_nonblank(title, details_text))
    if not source:
        return ""
    cleaned = source
    patterns = [
        r"【[^】]*】",
        r"\[[^\]]*\]",
        r"\([^)]*(?:美品|新品|未使用|中古|帯|初版|特典|送料無料|匿名配送|メルカリ)[^)]*\)",
        r"\b(?:vol(?:ume)?s?\.?)\s*\d+\s*(?:-|~|to|through)\s*\d+\b",
        r"\b\d+\s*(?:-|~|to|through)\s*\d+\s*(?:vol(?:ume)?s?|books?)\b",
        r"\b(?:vol(?:ume)?s?\.?)\s*\d+\b",
        r"\bby\s+[A-Z][A-Za-z .'\-]{1,70}$",
        r"\s+by\s+メルカリ\b",
        r"\b\d+\s*(?:book|books|volume|volumes|vols?\.?)\s*(?:complete\s*)?set\b",
        r"\b(?:complete|completed|full|all)\s*(?:manga|comic|comics)?\s*(?:set|series|volumes|vols)?\b",
        r"\b(?:manga|comic|comics|set|lot|bundle|reprint edition|box|boxed set)\b",
        r"\b(?:excellent|good|very good|used|new|sealed|shrink wrap|with shrink wrap)\s*(?:condition)?\b",
        r"\b(?:collector's edition|full color edition)\b",
        r"美品|番外編|おまけ|特典|限定|初版|新品|未使用|中古|全巻|フルセット|完結|セット|まとめ|漫画|マンガ|コミック|メルカリ",
        r"(?:全|完結)\s*\d{1,3}\s*(?:巻|卷|冊|册)",
        r"\d{1,3}\s*(?:巻|卷|冊|册)\s*(?:セット|まとめ|全巻)?",
    ]
    for pattern in patterns:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.I)
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = cleaned.strip(" -_/.,:;()[]{}｜|「」『』")
    return cleaned[:120] if len(cleaned) >= 2 else ""


def extract_volume_count_from_reference_text(text: object) -> Optional[int]:
    source = normalize_count_text(text)
    patterns = [
        r"\bVolumes?\s*[:：]?\s*(\d{1,3})\b",
        r"\bNo\.\s*of\s*volumes\s*[:：]?\s*(\d{1,3})\b",
        r"\bTankobon\s*volumes?\s*[:：]?\s*(\d{1,3})\b",
        r"巻数\s*[:：]?\s*(\d{1,3})\s*巻",
        r"全\s*(\d{1,3})\s*巻",
        r"(\d{1,3})\s*巻(?:既刊|完結|刊行)",
    ]
    for pattern in patterns:
        match = re.search(pattern, source, flags=re.I)
        if match:
            count = int(match.group(1))
            if 1 <= count <= 300:
                return count
    return None


@lru_cache(maxsize=256)
def anilist_manga_volume_lookup(query: str) -> ReferenceBookCountResult:
    query = clean_text(query)
    if not query or requests is None:
        return ReferenceBookCountResult(status="AniList lookup unavailable", query=query)
    graphql = """
    query ($search: String) {
      Page(page: 1, perPage: 5) {
        media(search: $search, type: MANGA) {
          title { romaji english native }
          volumes
          status
          format
          siteUrl
        }
      }
    }
    """
    try:
        response = requests.post(
            "https://graphql.anilist.co",
            json={"query": graphql, "variables": {"search": query}},
            headers={"User-Agent": "comic-ficp-streamlit-app/1.0 (local CSV enrichment)"},
            timeout=8,
        )
        response.raise_for_status()
        media_items = response.json().get("data", {}).get("Page", {}).get("media", [])
    except Exception as error:
        return ReferenceBookCountResult(status=f"AniList lookup failed: {redact_sensitive_text(error)}", query=query)

    query_key = normalize_key(query)
    for item in media_items:
        titles = item.get("title", {}) or {}
        title_values = [clean_text(titles.get(key, "")) for key in ("romaji", "english", "native")]
        title_keys = [normalize_key(value) for value in title_values if value]
        if not title_keys:
            continue
        title_match = any(query_key == key or query_key in key or key in query_key for key in title_keys)
        raw_count = item.get("volumes")
        try:
            count = int(raw_count)
        except Exception:
            count = 0
        if title_match and 1 <= count <= 300:
            matched_title = first_nonblank(*title_values)
            status = clean_text(item.get("status", ""))
            confidence = "high" if any(query_key == key for key in title_keys) else "medium"
            return ReferenceBookCountResult(
                status=f"AniList volume count found ({status or 'status unknown'})",
                book_count=count,
                source="AniList",
                confidence=confidence,
                evidence=f"{matched_title}: {count} volumes",
                query=query,
            )
    return ReferenceBookCountResult(status="AniList volume count not found", source="AniList", query=query)


@lru_cache(maxsize=256)
def mediawiki_manga_volume_lookup(query: str) -> ReferenceBookCountResult:
    query = clean_text(query)
    if not query or requests is None:
        return ReferenceBookCountResult(status="MediaWiki lookup unavailable", query=query)
    headers = {"User-Agent": "comic-ficp-streamlit-app/1.0 (local CSV enrichment)"}
    targets = [
        ("Wikipedia", "https://en.wikipedia.org/w/api.php", f"{query} manga"),
        ("Japanese Wikipedia", "https://ja.wikipedia.org/w/api.php", f"{query} 漫画"),
    ]
    for source_name, endpoint, search_text in targets:
        try:
            search_response = requests.get(
                endpoint,
                params={
                    "action": "query",
                    "list": "search",
                    "srsearch": search_text,
                    "srlimit": 3,
                    "format": "json",
                },
                headers=headers,
                timeout=8,
            )
            search_response.raise_for_status()
            pages = search_response.json().get("query", {}).get("search", [])
        except Exception as error:
            continue
        for page in pages:
            title = clean_text(page.get("title", ""))
            if title and not re.search(r"manga|漫画|コミック|volume|巻", f"{title} {page.get('snippet', '')}", flags=re.I):
                continue
            try:
                extract_response = requests.get(
                    endpoint,
                    params={
                        "action": "query",
                        "prop": "extracts",
                        "explaintext": 1,
                        "exintro": 0,
                        "titles": title,
                        "format": "json",
                    },
                    headers=headers,
                    timeout=8,
                )
                extract_response.raise_for_status()
                page_data = next(iter(extract_response.json().get("query", {}).get("pages", {}).values()), {})
            except Exception:
                continue
            extract = clean_text(page_data.get("extract", ""))
            count = extract_volume_count_from_reference_text(extract)
            if count:
                return ReferenceBookCountResult(
                    status=f"{source_name} volume count found",
                    book_count=count,
                    source=source_name,
                    confidence="medium",
                    evidence=f"{title}: {count} volumes",
                    query=query,
                )
    return ReferenceBookCountResult(status="MediaWiki volume count not found", source="MediaWiki", query=query)


def lookup_complete_set_book_count(
    title: str,
    details_text: str,
    combined_text: str,
    enable_reference_lookup: bool,
) -> ReferenceBookCountResult:
    source = normalize_count_text(combined_text)
    if not has_complete_set_claim(source):
        return ReferenceBookCountResult(
            status="skipped: no complete-set claim",
            source="rule",
            confidence="none",
            evidence="Book count unavailable and no complete-set claim",
        )

    local_count, local_evidence = detect_book_count_from_reference(source)
    if local_count:
        return ReferenceBookCountResult(
            status="local reference count found",
            book_count=local_count,
            source="Local reference data",
            confidence="high",
            evidence=local_evidence,
            query=infer_known_alias(source, SERIES_ALIASES),
        )

    query = infer_series_title_for_book_count_reference(title, details_text, combined_text)
    if not query:
        return ReferenceBookCountResult(
            status="skipped: series title could not be identified",
            source="rule",
            confidence="none",
            evidence="Series title could not be identified",
        )
    if not enable_reference_lookup:
        return ReferenceBookCountResult(
            status="skipped: free reference lookup disabled",
            source="rule",
            confidence="none",
            evidence="Complete-set count reference not found because free reference lookup is disabled",
            query=query,
        )

    anilist_result = anilist_manga_volume_lookup(query)
    if anilist_result.book_count and anilist_result.confidence in {"high", "medium"}:
        return anilist_result
    wiki_result = mediawiki_manga_volume_lookup(query)
    if wiki_result.book_count and wiki_result.confidence in {"high", "medium"}:
        return wiki_result
    return ReferenceBookCountResult(
        status="complete-set count reference not found",
        source="free reference lookup",
        confidence="none",
        evidence="Complete-set count reference not found",
        query=query,
    )


def exclusion_reason_for_missing_book_count(reference_result: ReferenceBookCountResult) -> tuple[str, str]:
    status = reference_result.status.lower()
    if "no complete-set claim" in status:
        return "Book count unavailable and no complete-set claim", reference_result.evidence
    if "series title could not be identified" in status:
        return "Series title could not be identified", reference_result.evidence
    return "Complete-set count reference not found", reference_result.evidence or reference_result.status


def apply_reference_count_result_to_row(row: pd.Series, reference_result: ReferenceBookCountResult) -> pd.Series:
    row["Reference Book Count"] = str(reference_result.book_count or "")
    row["Reference Count Source"] = reference_result.source
    row["Reference Count Confidence"] = reference_result.confidence
    row["Reference Count Evidence"] = reference_result.evidence
    row["Reference Count Status"] = reference_result.status
    return row


def detect_book_count_with_references(text: object) -> tuple[Optional[int], str]:
    book_count, evidence = detect_book_count(text)
    if book_count:
        return book_count, evidence
    return detect_book_count_from_reference(text)


def detect_book_count_limit_issue(book_count: Optional[int], max_book_count: int) -> ListingExclusion:
    limit = int(max_book_count or 0)
    if limit <= 0 or not book_count or book_count <= limit:
        return ListingExclusion()
    return ListingExclusion(
        excluded=True,
        reason="Book count exceeds export limit",
        evidence=f"{book_count} books detected; export limit is {limit} books.",
    )


def calculate_weight_kg(
    book_count: Optional[int],
    book_weight_g: int = DEFAULT_BOOK_WEIGHT_G,
    packaging_weight_kg: float = DEFAULT_PACKAGING_WEIGHT_KG,
) -> Optional[float]:
    if not book_count:
        return None
    # 重量計算: 冊数 x 1冊あたり推定重量(g) をkgへ変換し、商品ごとに推定した梱包材重量を加算します。
    # FedExは実重量と容積重量の大きい方を採用するため、ここでは「実重量」側の概算を作ります。
    total = (book_count * book_weight_g / 1000.0) + packaging_weight_kg
    return round(total, 3)


def estimate_book_weight_g(text: object, fallback_weight_g: int = DEFAULT_BOOK_WEIGHT_G) -> BookWeightEstimate:
    source = clean_text(text)
    lowered = source.lower()
    candidates: list[tuple[int, int, str]] = []

    def add_candidate(score: int, weight_g: int, evidence: str) -> None:
        candidates.append((score, weight_g, evidence))

    large_edition_keywords = [
        "完全版",
        "愛蔵版",
        "豪華版",
        "ワイド版",
        "大判",
        "大型",
        "collector's edition",
        "collectors edition",
        "complete edition",
        "deluxe",
        "wide edition",
        "omnibus",
        "aizoban",
        "kanzenban",
    ]
    if any(keyword in lowered or keyword in source for keyword in large_edition_keywords):
        add_candidate(120, WEIGHT_LARGE_EDITION_G, "large/special edition keyword")

    bunko_keywords = ["文庫版", "漫画文庫", "コミック文庫", "bunko", "bunkoban"]
    if any(keyword in lowered or keyword in source for keyword in bunko_keywords):
        add_candidate(115, WEIGHT_SMALL_BUNKO_G, "bunko/small format keyword")

    seinen_keywords = [
        "ヤングマガジン",
        "ヤンマガ",
        "young magazine",
        "ヤングジャンプ",
        "young jump",
        "ビッグコミックス",
        "big comics",
        "モーニング",
        "morning kc",
        "アフタヌーン",
        "afternoon kc",
        "イブニング",
        "evening kc",
        "seinen",
        "b6",
        "B6",
    ]
    if any(keyword in lowered or keyword in source for keyword in seinen_keywords):
        add_candidate(100, WEIGHT_STANDARD_SEINEN_G, "seinen/B6 magazine or imprint keyword")

    shonen_keywords = [
        "ジャンプコミックス",
        "少年ジャンプ",
        "週刊少年ジャンプ",
        "jump comics",
        "shonen jump",
        "少年マガジン",
        "週刊少年マガジン",
        "shonen magazine",
        "講談社コミックス",
        "kc comics",
        "少年サンデー",
        "shonen sunday",
        "新書判",
        "shonen",
    ]
    if any(keyword in lowered or keyword in source for keyword in shonen_keywords):
        add_candidate(90, WEIGHT_STANDARD_SHONEN_G, "shonen/new-book-size imprint keyword")

    shojo_keywords = [
        "少女漫画",
        "shojo",
        "shoujo",
        "マーガレット",
        "りぼん",
        "花とゆめ",
        "別冊マーガレット",
        "betsuma",
        "dessert kc",
    ]
    if any(keyword in lowered or keyword in source for keyword in shojo_keywords):
        add_candidate(85, WEIGHT_STANDARD_SHOJO_G, "shojo imprint/genre keyword")

    for series_title, aliases in SERIES_ALIASES.items():
        if not any(alias and alias.lower() in lowered for alias in aliases):
            continue
        reference = SERIES_REFERENCE_DATA.get(series_title, {})
        genre = str(reference.get("genre", ""))
        publisher = str(reference.get("publisher", ""))
        evidence_base = f"{series_title} reference"
        if re.search(r"\bseinen\b", genre, flags=re.I):
            add_candidate(96, WEIGHT_STANDARD_SEINEN_G, f"{evidence_base}: Seinen/B6-style comic")
        elif re.search(r"\bshonen\b", genre, flags=re.I):
            add_candidate(86, WEIGHT_STANDARD_SHONEN_G, f"{evidence_base}: Shonen comic")
        elif re.search(r"\bshojo\b", genre, flags=re.I):
            add_candidate(84, WEIGHT_STANDARD_SHOJO_G, f"{evidence_base}: Shojo comic")
        elif publisher in {"Shueisha", "Kodansha", "Shogakukan"}:
            add_candidate(70, fallback_weight_g, f"{evidence_base}: publisher known, format uncertain")

    if candidates:
        candidates.sort(key=lambda item: item[0], reverse=True)
        _, weight_g, evidence = candidates[0]
        return BookWeightEstimate(weight_g=weight_g, evidence=evidence)

    return BookWeightEstimate(weight_g=int(fallback_weight_g), evidence="fallback setting; no reliable format keyword")


def estimate_package_dimensions_cm(book_count: Optional[int]) -> tuple[float, float, float]:
    if not book_count:
        return 0.0, 0.0, 0.0
    length = DEFAULT_MANGA_HEIGHT_CM + DEFAULT_BOX_PADDING_CM
    width = DEFAULT_MANGA_WIDTH_CM + DEFAULT_BOX_PADDING_CM
    stacked_height = (book_count * DEFAULT_MANGA_THICKNESS_CM) + DEFAULT_BOX_EXTRA_HEIGHT_CM
    return round(length, 1), round(width, 1), round(stacked_height, 1)


def resolve_package_dimensions_cm(
    book_count: Optional[int],
    package_length_cm: float = 0.0,
    package_width_cm: float = 0.0,
    package_height_cm: float = 0.0,
) -> tuple[float, float, float, str]:
    provided = [float(package_length_cm or 0), float(package_width_cm or 0), float(package_height_cm or 0)]
    if all(value > 0 for value in provided):
        return round(provided[0], 1), round(provided[1], 1), round(provided[2], 1), "manual"
    length, width, height = estimate_package_dimensions_cm(book_count)
    if all(value > 0 for value in (length, width, height)):
        return length, width, height, "estimated"
    return 0.0, 0.0, 0.0, "none"


def estimate_packaging_weight_kg(
    book_count: Optional[int],
    length_cm: float = 0.0,
    width_cm: float = 0.0,
    height_cm: float = 0.0,
    fallback_weight_kg: float = DEFAULT_PACKAGING_WEIGHT_KG,
) -> PackagingEstimate:
    standard_materials = "bubble wrap; cardboard box; paper filler"
    reinforced_materials = "bubble wrap; reinforced cardboard box; paper filler"
    if not book_count:
        return PackagingEstimate(
            weight_kg=round(float(fallback_weight_kg or DEFAULT_PACKAGING_WEIGHT_KG), 3),
            materials=standard_materials,
            evidence="fallback setting; book count was not detected",
        )

    if book_count <= 3:
        base_weight = 0.18
        size_label = "small set"
        materials = "bubble wrap; compact cardboard mailer/box; paper filler"
    elif book_count <= 8:
        base_weight = 0.25
        size_label = "small-to-medium set"
        materials = standard_materials
    elif book_count <= 15:
        base_weight = 0.35
        size_label = "medium set"
        materials = standard_materials
    elif book_count <= 25:
        base_weight = 0.50
        size_label = "large set"
        materials = reinforced_materials
    elif book_count <= 40:
        base_weight = 0.70
        size_label = "heavy set"
        materials = reinforced_materials
    else:
        extra_blocks = math.ceil((book_count - 40) / 20)
        base_weight = 0.70 + (extra_blocks * 0.20)
        size_label = "very heavy set"
        materials = reinforced_materials

    volume = float(length_cm or 0) * float(width_cm or 0) * float(height_cm or 0)
    volume_adjustment = 0.0
    if volume >= 35000:
        volume_adjustment = 0.20
    elif volume >= 20000:
        volume_adjustment = 0.10

    weight = min(base_weight + volume_adjustment, 1.50)
    evidence = f"{book_count} books, {size_label}"
    if volume_adjustment:
        evidence += f"; larger estimated box volume added {volume_adjustment:.2f} kg"
    return PackagingEstimate(weight_kg=round(weight, 3), materials=materials, evidence=evidence)


def calculate_dimensional_weight_kg(
    length_cm: float,
    width_cm: float,
    height_cm: float,
    divisor: int = DEFAULT_DIMENSIONAL_DIVISOR_CM,
) -> Optional[float]:
    if divisor <= 0:
        raise ValueError("Dimensional divisor must be greater than 0")
    if length_cm <= 0 or width_cm <= 0 or height_cm <= 0:
        return None
    # FedExの容積重量: 各寸法(cm)を使い、長さ x 幅 x 高さ / 5000 でkg換算します。
    # 実運用ではFedEx側が寸法を端数切り上げすることがあるため、ここでは見積もりとして小数2桁に丸めます。
    return round((length_cm * width_cm * height_cm) / divisor, 3)


def calculate_billable_weight_kg(actual_weight_kg: Optional[float], dimensional_weight_kg: Optional[float]) -> tuple[Optional[float], str]:
    weights: list[tuple[float, str]] = []
    if actual_weight_kg and actual_weight_kg > 0:
        weights.append((actual_weight_kg, "actual"))
    if dimensional_weight_kg and dimensional_weight_kg > 0:
        weights.append((dimensional_weight_kg, "dimensional"))
    if not weights:
        return None, ""
    weight, source = max(weights, key=lambda item: item[0])
    return round(weight, 3), source


def round_up_half_kg(weight_kg: float) -> float:
    return max(0.5, math.ceil((weight_kg - 1e-9) * 2) / 2)


def calculate_ficp_shipping(weight_kg: float, zone: str) -> FICPCharge:
    zone = zone.upper().strip()
    if zone not in FICP_ZONES:
        raise ValueError(f"Unsupported FICP zone: {zone}")
    if weight_kg <= 0:
        raise ValueError("Weight must be greater than 0 kg")

    # FICP料金表の参照:
    # 32.5kgまでは0.5kg刻みの表を使うため、実重量を次の0.5kgへ切り上げます。
    # 33kg以上はPDF記載の「キログラム単位料金」を貨物総重量へ掛けて算出します。
    if weight_kg <= 32.5:
        billed_weight = round_up_half_kg(weight_kg)
        rate_row = FICP_STANDARD_RATES[billed_weight]
        return FICPCharge(
            zone=zone,
            input_weight_kg=weight_kg,
            billed_weight_kg=billed_weight,
            shipping_jpy=rate_row[zone],
            rate_type="table",
        )

    for lower, upper, rates in FICP_PER_KG_RATES:
        if lower <= weight_kg <= upper:
            per_kg_rate = rates[zone]
            return FICPCharge(
                zone=zone,
                input_weight_kg=weight_kg,
                billed_weight_kg=weight_kg,
                shipping_jpy=math.ceil(weight_kg * per_kg_rate),
                rate_type="per_kg",
                per_kg_rate_jpy=per_kg_rate,
            )

    raise ValueError("FICP table supports weights up to 99,999 kg")


def calculate_fuel_surcharge_jpy(base_shipping_jpy: int, fuel_surcharge_percent: float) -> int:
    if base_shipping_jpy <= 0:
        return 0
    percent = max(0.0, float(fuel_surcharge_percent or 0.0))
    return int(math.ceil(base_shipping_jpy * percent / 100))


def calculate_shipping_total_with_fuel(base_shipping_jpy: int, fuel_surcharge_percent: float) -> tuple[int, int]:
    fuel_surcharge_jpy = calculate_fuel_surcharge_jpy(base_shipping_jpy, fuel_surcharge_percent)
    return base_shipping_jpy + fuel_surcharge_jpy, fuel_surcharge_jpy


def jpy_to_usd(jpy: int, exchange_rate_jpy_per_usd: float) -> float:
    if exchange_rate_jpy_per_usd <= 0:
        raise ValueError("Exchange rate must be greater than 0")
    return round(jpy / exchange_rate_jpy_per_usd, 2)


def fetch_usd_jpy_exchange_rate() -> ExchangeRateEstimate:
    """無料公開APIからUSD/JPYを取得する。失敗時は理由をstatusへ入れて返す。"""
    if requests is None:
        return ExchangeRateEstimate(
            rate=DEFAULT_EXCHANGE_RATE_JPY_PER_USD,
            source="manual/default",
            date="",
            status="requests is not available; default rate was used",
        )

    headers = {"User-Agent": "comic-ficp-streamlit-app/1.0 (local CSV enrichment)"}
    errors: list[str] = []

    try:
        response = requests.get(
            "https://api.frankfurter.dev/v2/rates",
            params={"base": "USD", "quotes": "JPY"},
            headers=headers,
            timeout=8,
        )
        response.raise_for_status()
        payload = response.json()
        item = payload[0] if isinstance(payload, list) and payload else payload
        rate = float(item.get("rate") or item.get("rates", {}).get("JPY"))
        if rate > 0:
            return ExchangeRateEstimate(
                rate=round(rate, 4),
                source="Frankfurter",
                date=str(item.get("date", "")),
                status="ok",
            )
    except Exception as error:
        errors.append(f"Frankfurter: {error}")

    try:
        response = requests.get(
            "https://open.er-api.com/v6/latest/USD",
            headers=headers,
            timeout=8,
        )
        response.raise_for_status()
        payload = response.json()
        rate = float(payload.get("rates", {}).get("JPY"))
        if rate > 0:
            return ExchangeRateEstimate(
                rate=round(rate, 4),
                source="ExchangeRate-API open endpoint",
                date=str(payload.get("time_last_update_utc", "")),
                status="ok",
            )
    except Exception as error:
        errors.append(f"ExchangeRate-API: {error}")

    return ExchangeRateEstimate(
        rate=DEFAULT_EXCHANGE_RATE_JPY_PER_USD,
        source="manual/default",
        date="",
        status="; ".join(errors) or "exchange rate lookup failed; default rate was used",
    )


def ficp_us_zone_label(zone: str) -> str:
    zone = str(zone or "").upper().strip()
    if zone == "F":
        return "U.S. other / Canada / Puerto Rico (Zone F)"
    if zone == "E":
        return "U.S. western region (Zone E)"
    return f"Zone {zone}" if zone else ""


def extract_section_between_markers(text: str, start_marker: str, end_markers: Iterable[str]) -> str:
    source = str(text or "")
    start = source.find(start_marker)
    if start < 0:
        return ""
    start += len(start_marker)
    end = len(source)
    for marker in end_markers:
        marker_index = source.find(marker, start)
        if marker_index >= 0:
            end = min(end, marker_index)
    return clean_text(source[start:end])


def remove_mercari_relative_date_lines(text: str) -> str:
    text = re.sub(r"\s*(?:\d+\s*(?:秒|分|時間|日|週間|ヶ月|年)前|昨日|一昨日)\s*$", "", str(text or "")).strip()
    lines = []
    for line in text.splitlines():
        cleaned = clean_text(line)
        if not cleaned:
            continue
        if re.fullmatch(r"(?:\d+\s*(?:秒|分|時間|日|週間|ヶ月|年)前|昨日|一昨日)", cleaned):
            continue
        lines.append(cleaned)
    return "\n".join(lines)


def extract_mercari_condition_from_rendered_text(text: str) -> str:
    section = extract_section_between_markers(
        text,
        "商品の状態",
        ["配送料の負担", "配送の方法", "発送元の地域", "発送までの日数", "メルカリ安心", "出品者"],
    )
    lines = [clean_text(line) for line in section.splitlines() if clean_text(line)]
    return lines[0] if lines else ""


def parse_mercari_rendered_listing(
    *,
    url: str,
    page_title: str,
    body_text: str,
    image_url: str = "",
) -> ListingData:
    title = clean_text(re.sub(r"\s*-\s*メルカリ\s*$", "", page_title or ""))
    price_match = re.search(r"[\u00a5\uffe5]\s*([0-9,]+)", body_text or "")
    price = price_match.group(1) if price_match else ""
    description = extract_section_between_markers(body_text, "商品の説明", ["商品の情報"])
    description = remove_mercari_relative_date_lines(description)
    condition = extract_mercari_condition_from_rendered_text(body_text)
    item_info = extract_section_between_markers(
        body_text,
        "商品の情報",
        ["メルカリ安心", "出品者", "コメント", "他の人はこちらも検索"],
    )
    details_parts = [part for part in [description, f"商品の状態 {condition}" if condition else "", item_info] if part]
    status = "ok (browser rendered)" if description or condition or item_info else "browser rendered: listing detail not found"
    return ListingData(
        title=title[:300],
        price=clean_text(price)[:80],
        image_url=clean_text(image_url),
        description=description[:1800],
        details_text=clean_text("\n".join(details_parts))[:5000],
        status=status,
        source_url=url,
    )


class BrowserListingScraper:
    def __init__(self) -> None:
        self._playwright = None
        self._browser = None
        self._page = None

    def start(self) -> None:
        if self._page is not None:
            return
        if sync_playwright is None:
            raise RuntimeError("playwright is not installed")
        self._playwright = sync_playwright().start()
        launch_errors: list[str] = []
        for channel in ("chrome", "msedge", ""):
            try:
                launch_kwargs = {"headless": True}
                if channel:
                    launch_kwargs["channel"] = channel
                self._browser = self._playwright.chromium.launch(**launch_kwargs)
                break
            except Exception as error:
                launch_errors.append(f"{channel or 'bundled chromium'}: {error}")
        if self._browser is None:
            self.close()
            raise RuntimeError("; ".join(launch_errors) or "browser launch failed")
        self._page = self._browser.new_page(
            locale="ja-JP",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        )

    def scrape(self, url: str, timeout: int = 25) -> ListingData:
        self.start()
        try:
            self._page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
            try:
                self._page.wait_for_load_state("networkidle", timeout=12000)
            except Exception:
                pass
            try:
                self._page.get_by_text("商品の説明", exact=True).wait_for(timeout=12000)
            except Exception:
                self._page.wait_for_timeout(3000)
            body_text = self._page.locator("body").inner_text(timeout=10000)
            page_title = self._page.title()
            meta_values = self._page.evaluate(
                """() => ({
                    imageUrl: document.querySelector('meta[property="og:image"], meta[name="twitter:image"]')?.content || '',
                    price: document.querySelector('meta[property="product:price:amount"], meta[property="product:price"]')?.content || ''
                })"""
            )
            listing = parse_mercari_rendered_listing(
                url=url,
                page_title=page_title,
                body_text=body_text,
                image_url=meta_values.get("imageUrl", "") if isinstance(meta_values, dict) else "",
            )
            if not listing.price and isinstance(meta_values, dict):
                listing.price = clean_text(meta_values.get("price", ""))[:80]
            if (not listing.price or not listing.image_url) and BeautifulSoup is not None:
                html = self._page.content()
                static_payload = extract_listing_payload(BeautifulSoup(html, "lxml"), html)
                listing.price = first_nonblank(listing.price, static_payload.price)
                listing.image_url = first_nonblank(listing.image_url, static_payload.image_url)
            return listing
        except Exception as error:
            return ListingData(source_url=url, status=f"browser fetch failed: {error}")

    def close(self) -> None:
        for target in (self._page, self._browser):
            try:
                if target is not None:
                    target.close()
            except Exception:
                pass
        self._page = None
        self._browser = None
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                pass
        self._playwright = None


def scrape_listing(
    url: str,
    timeout: int = 14,
    use_browser: bool = False,
    browser_scraper: Optional[BrowserListingScraper] = None,
) -> ListingData:
    url = str(url or "").strip()
    if not url:
        return ListingData(status="no url")
    browser_status = ""
    if use_browser and is_mercari_listing_url(url):
        temporary_browser_scraper = None
        try:
            temporary_browser_scraper = None if browser_scraper is not None else BrowserListingScraper()
            rendered = (browser_scraper or temporary_browser_scraper).scrape(url, timeout=max(timeout, 25))
            if rendered.description or extract_mercari_condition_from_rendered_text(rendered.details_text):
                return rendered
            browser_status = rendered.status
        except Exception as error:
            browser_status = f"browser fetch failed: {error}"
        finally:
            if temporary_browser_scraper is not None:
                temporary_browser_scraper.close()
    if requests is None or BeautifulSoup is None:
        return ListingData(source_url=url, status="missing requests/beautifulsoup4")

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return ListingData(source_url=url, status="unsupported url")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ja,en-US;q=0.8,en;q=0.6",
        "Referer": f"{parsed.scheme}://{parsed.netloc}/",
    }

    try:
        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
    except Exception as error:
        status = f"fetch failed: {error}"
        if browser_status:
            status = f"{browser_status}; {status}"
        return ListingData(source_url=url, status=status)

    soup = BeautifulSoup(response.text, "lxml")
    payload = extract_listing_payload(soup, response.text)
    payload.source_url = url
    payload.status = "ok" if not browser_status else f"ok; {browser_status}"
    return payload


def extract_listing_payload(soup, html: str) -> ListingData:
    title = first_nonblank(
        meta_content(soup, "property", "og:title"),
        meta_content(soup, "name", "twitter:title"),
        soup.title.string if soup.title else "",
    )
    description = first_nonblank(
        meta_content(soup, "property", "og:description"),
        meta_content(soup, "name", "description"),
        meta_content(soup, "name", "twitter:description"),
    )
    image_url = first_nonblank(
        meta_content(soup, "property", "og:image"),
        meta_content(soup, "name", "twitter:image"),
    )
    price = first_nonblank(
        meta_content(soup, "property", "product:price:amount"),
        meta_content(soup, "property", "product:price"),
    )

    json_ld = extract_json_ld_product_data(soup)
    title = first_nonblank(json_ld.get("title"), title)
    description = first_nonblank(json_ld.get("description"), description)
    image_url = first_nonblank(json_ld.get("image_url"), image_url)
    price = first_nonblank(json_ld.get("price"), price, regex_first(html, r'"price"\s*:\s*"?([0-9,]+)"?'))

    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    visible_text = clean_text(soup.get_text(" "))

    return ListingData(
        title=clean_text(title)[:300],
        price=clean_text(price)[:80],
        image_url=clean_text(image_url),
        description=clean_text(description)[:1800],
        details_text=visible_text[:5000],
    )


def meta_content(soup, attr: str, value: str) -> str:
    tag = soup.find("meta", attrs={attr: value})
    return clean_text(tag.get("content", "")) if tag else ""


def regex_first(text: str, pattern: str) -> str:
    match = re.search(pattern, text, flags=re.I | re.S)
    return clean_text(match.group(1)) if match else ""


def extract_json_ld_product_data(soup) -> dict[str, str]:
    result: dict[str, str] = {}
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text() or ""
        if not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        for node in walk_json(data):
            node_type = node.get("@type")
            if isinstance(node_type, list):
                is_product = any(str(item).lower() == "product" for item in node_type)
            else:
                is_product = str(node_type or "").lower() == "product"
            if not is_product:
                continue
            result["title"] = first_nonblank(result.get("title"), node.get("name"))
            result["description"] = first_nonblank(result.get("description"), node.get("description"))
            image = node.get("image")
            if isinstance(image, list):
                image = first_nonblank(*image)
            result["image_url"] = first_nonblank(result.get("image_url"), image)
            offers = node.get("offers")
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            if isinstance(offers, dict):
                result["price"] = first_nonblank(result.get("price"), offers.get("price"))
    return result


def walk_json(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


KNOWN_PUBLISHERS = [
    ("Shueisha", "集英社"),
    ("Kodansha", "講談社"),
    ("Shogakukan", "小学館"),
    ("Kadokawa", "KADOKAWA"),
    ("Square Enix", "スクウェア・エニックス"),
    ("Hakusensha", "白泉社"),
    ("Akita Shoten", "秋田書店"),
    ("Futabasha", "双葉社"),
    ("Shinchosha", "新潮社"),
    ("Tokuma Shoten", "徳間書店"),
    ("Ichijinsha", "一迅社"),
    ("Media Factory", "メディアファクトリー"),
    ("ASCII Media Works", "アスキー・メディアワークス"),
]

PUBLISHER_ALIASES = {
    "Shueisha": ["集英社", "Shueisha", "Jump Comics", "ジャンプコミックス", "少年ジャンプ"],
    "Kodansha": ["講談社", "Kodansha", "週刊少年マガジン", "Morning KC"],
    "Shogakukan": ["小学館", "Shogakukan", "少年サンデー", "Big Comics"],
    "Kadokawa": ["KADOKAWA", "角川", "Kadokawa"],
    "Square Enix": ["スクウェア・エニックス", "Square Enix", "ガンガン"],
    "Hakusensha": ["白泉社", "Hakusensha", "花とゆめ"],
    "Akita Shoten": ["秋田書店", "Akita Shoten"],
    "Futabasha": ["双葉社", "Futabasha"],
    "Shinchosha": ["新潮社", "Shinchosha"],
    "Tokuma Shoten": ["徳間書店", "Tokuma Shoten"],
    "Ichijinsha": ["一迅社", "Ichijinsha"],
    "Media Factory": ["メディアファクトリー", "Media Factory"],
    "ASCII Media Works": ["アスキー・メディアワークス", "ASCII Media Works"],
}

SERIES_ALIASES = {
    "Daytime Shooting Star": ["ひるなかの流星", "Hirunaka no Ryuusei", "Hirunaka no Ryusei", "Daytime Shooting Star"],
    "Banana Fish": ["BANANA FISH", "Banana Fish"],
    "Pineapple Army": ["PINEAPPLE ARMY", "Pineapple Army"],
    "Blue Lock": ["Blue Lock", "ブルーロック"],
    "Jujutsu Kaisen": ["呪術廻戦", "Jujutsu Kaisen"],
    "Chainsaw Man": ["チェンソーマン", "Chainsaw Man"],
    "One Piece": ["ワンピース", "ONE PIECE", "One Piece"],
    "Naruto": ["ナルト", "NARUTO", "Naruto"],
    "Demon Slayer": ["鬼滅の刃", "Demon Slayer", "Kimetsu no Yaiba"],
    "Attack on Titan": ["進撃の巨人", "Attack on Titan", "Shingeki no Kyojin"],
    "My Hero Academia": ["僕のヒーローアカデミア", "My Hero Academia"],
    "Haikyu!!": ["ハイキュー", "Haikyu", "Haikyu!!"],
    "Tokyo Revengers": ["東京リベンジャーズ", "Tokyo Revengers"],
    "Spy x Family": ["SPY×FAMILY", "SPY x FAMILY", "Spy x Family"],
    "Dragon Ball": ["ドラゴンボール", "Dragon Ball", "DRAGON BALL"],
    "Tokyo Ghoul:re": ["東京喰種:re", "Tokyo Ghoul:re", "Tokyo Ghoulre", "Tokyo Ghoul re"],
    "Gag Manga Biyori": ["ギャグマンガ日和", "Gag Manga Biyori", "Original Gag Manga Biyori"],
    "Bakemonogatari": ["化物語", "Bakemonogatari"],
    "The Quintessential Quintuplets": ["五等分の花嫁", "The Quintessential Quintuplets", "Quintessential Quintuplets"],
    "A Silent Voice": ["聲の形", "A Silent Voice", "silent Voice"],
    "Akane-banashi": ["あかね噺", "Akane-banashi", "Akane banashi"],
    "Radiation House": ["ラジエーションハウス", "Radiation House"],
    "Kasane": ["累", "Kasane"],
    "Honey": ["ハニー", "Amu Meguro Honey", "Honey Complete"],
    "Hajimete no Aku": ["はじめてのあく", "Hajimete no Aku"],
    "Records of the Grand Historian": ["横山光輝 史記", "Mitsuteru Yokoyama, Shiki", "Shiki, Collector"],
    "Mozuya-san Gets Angry": ["Mozuya Gets Angry", "Mozuya-san Gets Angry", "Mozuya-san Gyakujou", "Mozuya-san Gyakujousuru"],
    "Li'l Miss Vampire Can't Suck Right": [
        "The teacher is a vampire who is bad at kissing",
        "Li'l Miss Vampire Can't Suck Right",
        "Lil Miss Vampire Cant Suck Right",
        "Chanto Suenai Kyuketsuki-chan",
        "Chanto Suenai Kyuuketsuki-chan",
    ],
    "Kijima-san and Yamada-san": ["Onijima-san and Yamada-san", "Kijima-san and Yamada-san", "Kijima-san & Yamada-san"],
    "You Might As Well Be the One": ["Megumu Seto, Just Kill Me", "Just Kill Me", "You Might As Well Be the One", "Isso Anata ga Todome wo Sashite"],
    "Tamon's B-Side": ["Tamonten-kun, Which Way is He Going", "Tamonten-kun", "Tamon-kun Ima Dotchi", "Tamon's B-Side", "Tamons B-Side"],
    "Kingdom": ["キングダム", "Kingdom"],
    "Slam Dunk": ["スラムダンク", "Slam Dunk"],
    "Food Wars!: Shokugeki no Soma": ["食戟のソーマ", "Food Wars", "Shokugeki no Soma"],
}

AUTHOR_ALIASES = {
    "Mika Yamamori": ["やまもり三香", "Yamamori Mika", "Mika Yamamori"],
    "Akimi Yoshida": ["吉田秋生", "Akimi Yoshida"],
    "Kazuya Kudo; Naoki Urasawa": ["工藤かずや", "浦沢直樹", "Kazuya Kudo, Naoki Urasawa", "Kazuya Kudo; Naoki Urasawa"],
    "Muneyuki Kaneshiro; Yusuke Nomura": ["金城宗幸", "ノ村優介", "Muneyuki Kaneshiro", "Yusuke Nomura"],
    "Gege Akutami": ["芥見下々", "Gege Akutami"],
    "Tatsuki Fujimoto": ["藤本タツキ", "Tatsuki Fujimoto"],
    "Eiichiro Oda": ["尾田栄一郎", "Eiichiro Oda"],
    "Akira Toriyama": ["鳥山明", "Akira Toriyama"],
    "Masashi Kishimoto": ["岸本斉史", "Masashi Kishimoto"],
    "Koyoharu Gotouge": ["吾峠呼世晴", "Koyoharu Gotouge"],
    "Tatsuya Endo": ["遠藤達哉", "遠藤 達哉", "Tatsuya Endo", "Tatsuya Endō"],
    "Sui Ishida": ["石田スイ", "Sui Ishida"],
    "Kosuke Masuda": ["増田こうすけ", "Kosuke Masuda", "Kousuke Masuda"],
    "Nisio Isin; Oh! great": ["西尾維新", "大暮維人", "Nisio Isin", "Oh! great", "Oh great"],
    "Negi Haruba": ["春場ねぎ", "Negi Haruba"],
    "Yoshitoki Oima": ["大今良時", "Yoshitoki Oima", "Yoshitoki Ooima"],
    "Yuki Suenaga; Takamasa Moue": ["末永裕樹", "馬上鷹将", "Yuki Suenaga", "Takamasa Moue"],
    "Tomohiro Yokomaku; Taishi Mori": ["横幕智裕", "モリタイシ", "Tomohiro Yokomaku", "Taishi Mori"],
    "Daruma Matsuura": ["松浦だるま", "Daruma Matsuura"],
    "Amu Meguro": ["目黒あむ", "Amu Meguro"],
    "Shun Fujiki": ["藤木俊", "Shun Fujiki"],
    "Mitsuteru Yokoyama": ["横山光輝", "Mitsuteru Yokoyama"],
    "Rokuro Shinofusa": ["Rokuro Shinofusa", "Shinofusa Rokuro"],
    "Kyosuke Nishiki": ["Kyosuke Nishiki", "Kyousuke Nishiki"],
    "Hoshimi SK": ["Hoshimi SK", "Hoshimi Sk"],
    "Megumu Seto": ["Megumu Seto"],
    "Yuki Shiwasu": ["Yuki Shiwasu"],
    "Uzu Natsuno": ["Uzu Natsuno"],
    "Yuto Tsukuda; Shun Saeki": ["附田祐斗", "佐伯俊", "Yuto Tsukuda", "Shun Saeki"],
}

SERIES_REFERENCE_DATA = {
    "Daytime Shooting Star": {
        "author": "Mika Yamamori",
        "publisher": "Shueisha",
        "genre": "Shojo",
        "characters": "Suzume Yosano; Daiki Mamura; Satsuki Shishio",
        "publication_year": "2011",
    },
    "Jujutsu Kaisen": {
        "author": "Gege Akutami",
        "publisher": "Shueisha",
        "genre": "Shonen",
        "characters": "Yuji Itadori; Megumi Fushiguro; Nobara Kugisaki; Satoru Gojo",
        "publication_year": "2018",
    },
    "Chainsaw Man": {
        "author": "Tatsuki Fujimoto",
        "publisher": "Shueisha",
        "genre": "Shonen",
        "characters": "Denji; Power; Makima; Aki Hayakawa",
        "publication_year": "2018",
    },
    "One Piece": {
        "author": "Eiichiro Oda",
        "publisher": "Shueisha",
        "genre": "Action, Adventure, Shonen",
        "characters": "Monkey D. Luffy; Roronoa Zoro; Nami; Sanji",
        "publication_year": "1997",
    },
    "Naruto": {
        "author": "Masashi Kishimoto",
        "publisher": "Shueisha",
        "genre": "Action, Adventure, Shonen",
        "characters": "Naruto Uzumaki; Sasuke Uchiha; Sakura Haruno; Kakashi Hatake",
        "publication_year": "1999",
    },
    "Dragon Ball": {
        "author": "Akira Toriyama",
        "publisher": "Shueisha",
        "genre": "Action, Adventure, Martial Arts, Shonen",
        "characters": "Son Goku; Bulma; Vegeta; Piccolo",
        "publication_year": "1984",
    },
    "Demon Slayer": {
        "author": "Koyoharu Gotouge",
        "publisher": "Shueisha",
        "genre": "Action, Dark Fantasy, Shonen",
        "characters": "Tanjiro Kamado; Nezuko Kamado; Zenitsu Agatsuma; Inosuke Hashibira",
        "publication_year": "2016",
    },
    "Attack on Titan": {
        "author": "Hajime Isayama",
        "publisher": "Kodansha",
        "genre": "Shonen",
        "characters": "Eren Yeager; Mikasa Ackerman; Armin Arlert; Levi Ackerman",
        "publication_year": "2009",
    },
    "Banana Fish": {
        "author": "Akimi Yoshida",
        "publisher": "Shogakukan",
        "genre": "Action, Crime, Drama, Shojo",
        "characters": "Ash Lynx; Eiji Okumura",
        "publication_year": "1985",
        "complete_volume_count": 19,
    },
    "Pineapple Army": {
        "author": "Kazuya Kudo; Naoki Urasawa",
        "publisher": "Shogakukan",
        "genre": "Action, Adventure, Seinen",
        "characters": "Jed Goshi",
        "publication_year": "1985",
    },
    "Blue Lock": {
        "author": "Muneyuki Kaneshiro; Yusuke Nomura",
        "publisher": "Kodansha",
        "genre": "Sports, Drama, Shonen",
        "characters": "Yoichi Isagi; Meguru Bachira; Seishiro Nagi; Rin Itoshi",
        "publication_year": "2018",
    },
    "Tokyo Ghoul:re": {
        "author": "Sui Ishida",
        "publisher": "Shueisha",
        "genre": "Dark Fantasy, Horror, Seinen",
        "characters": "Ken Kaneki; Haise Sasaki; Touka Kirishima",
        "publication_year": "2014",
    },
    "Gag Manga Biyori": {
        "author": "Kosuke Masuda",
        "publisher": "Shueisha",
        "genre": "Comedy, Shonen",
        "characters": "Various",
        "publication_year": "2000",
    },
    "Bakemonogatari": {
        "author": "Nisio Isin; Oh! great",
        "publisher": "Kodansha",
        "genre": "Supernatural, Comedy, Shonen",
        "characters": "Koyomi Araragi; Hitagi Senjougahara; Shinobu Oshino",
        "publication_year": "2018",
    },
    "The Quintessential Quintuplets": {
        "author": "Negi Haruba",
        "publisher": "Kodansha",
        "genre": "Romantic Comedy, Shonen",
        "characters": "Futaro Uesugi; Ichika Nakano; Nino Nakano; Miku Nakano; Yotsuba Nakano; Itsuki Nakano",
        "publication_year": "2017",
        "complete_volume_count": 14,
    },
    "A Silent Voice": {
        "author": "Yoshitoki Oima",
        "publisher": "Kodansha",
        "genre": "Drama, Romance, Shonen",
        "characters": "Shoya Ishida; Shoko Nishimiya",
        "publication_year": "2013",
        "complete_volume_count": 7,
    },
    "Akane-banashi": {
        "author": "Yuki Suenaga; Takamasa Moue",
        "publisher": "Shueisha",
        "genre": "Drama, Comedy, Shonen",
        "characters": "Akane Osaki",
        "publication_year": "2022",
    },
    "Radiation House": {
        "author": "Tomohiro Yokomaku; Taishi Mori",
        "publisher": "Shueisha",
        "genre": "Medical Drama, Seinen",
        "characters": "Iori Igarashi; An Amakasu",
        "publication_year": "2015",
    },
    "Kasane": {
        "author": "Daruma Matsuura",
        "publisher": "Kodansha",
        "genre": "Psychological Thriller, Drama, Seinen",
        "characters": "Kasane Fuchi",
        "publication_year": "2013",
    },
    "Honey": {
        "author": "Amu Meguro",
        "publisher": "Shueisha",
        "genre": "Romance, Shojo",
        "characters": "Nao Kogure; Taiga Onise",
        "publication_year": "2012",
    },
    "Hajimete no Aku": {
        "author": "Shun Fujiki",
        "publisher": "Shogakukan",
        "genre": "Comedy, Romance, Shonen",
        "characters": "Jiro Aku; Kyoko Naruse",
        "publication_year": "2009",
    },
    "Records of the Grand Historian": {
        "author": "Mitsuteru Yokoyama",
        "publisher": "Shogakukan",
        "genre": "Historical, Drama",
        "characters": "Various",
        "publication_year": "1992",
    },
    "Mozuya-san Gets Angry": {
        "author": "Rokuro Shinofusa",
        "publisher": "Kodansha",
        "genre": "Comedy, Romance, Seinen",
        "characters": "Koto Mozuya",
        "publication_year": "2008",
    },
    "Li'l Miss Vampire Can't Suck Right": {
        "author": "Kyosuke Nishiki",
        "publisher": "Fujimi Shobo",
        "genre": "Comedy, Supernatural, Shonen",
        "characters": "Luna Ishikawa; Tatsuta Ootori",
        "publication_year": "2021",
    },
    "Kijima-san and Yamada-san": {
        "author": "Hoshimi SK",
        "publisher": "Square Enix",
        "genre": "Romance, Comedy",
        "characters": "Kijima; Yamada",
        "publication_year": "2019",
    },
    "You Might As Well Be the One": {
        "author": "Megumu Seto",
        "publisher": "Kodansha",
        "genre": "Romance, Shojo",
        "characters": "Ichika Nakajo; Kosei Sanari",
        "publication_year": "2023",
    },
    "Tamon's B-Side": {
        "author": "Yuki Shiwasu",
        "publisher": "Hakusensha",
        "genre": "Romantic Comedy, Shojo",
        "characters": "Tamon Fukuhara; Utage Kinoshita",
        "publication_year": "2021",
    },
    "My Hero Academia": {
        "author": "Kohei Horikoshi",
        "publisher": "Shueisha",
        "genre": "Shonen",
        "characters": "Izuku Midoriya; Katsuki Bakugo; All Might; Shoto Todoroki",
        "publication_year": "2014",
    },
    "Spy x Family": {
        "author": "Tatsuya Endo",
        "publisher": "Shueisha",
        "genre": "Action, Comedy, Slice of Life, Shonen",
        "characters": "Loid Forger; Anya Forger; Yor Forger; Bond Forger",
        "publication_year": "2019",
    },
    "Food Wars!: Shokugeki no Soma": {
        "author": "Yuto Tsukuda; Shun Saeki",
        "publisher": "Shueisha",
        "genre": "Cooking, Comedy, Shonen",
        "characters": "Soma Yukihira; Erina Nakiri; Megumi Tadokoro",
        "publication_year": "2012",
        "complete_volume_count": 36,
    },
}


def add_specific_value(
    specifics: dict[str, str],
    notes: list[str],
    candidate_columns: Iterable[str],
    aliases: Iterable[str],
    value: str,
    reason: str,
) -> None:
    value = clean_text(value)
    if not value:
        return
    alias_keys = {normalize_key(alias) for alias in aliases}
    matched: list[str] = []
    for column in candidate_columns:
        if normalized_specific_name(column) in alias_keys:
            specifics[column] = value
            matched.append(column)
    if matched:
        notes.append(f"{', '.join(matched)}={value} ({reason})")


def build_ai_enrichment_prompt(
    *,
    title: str,
    description: str,
    details_text: str,
    candidate_columns: Iterable[str],
    book_count: Optional[int],
) -> str:
    allowed_columns = ", ".join(get_specific_columns(candidate_columns, include_defaults=True))
    return "\n".join(
        [
            "You enrich an eBay manga/comic book set CSV row.",
            "Return JSON only, with this shape:",
            '{"book_count":null,"book_count_evidence":"","description_notes":["English buyer-facing fact"],"specifics":{"C:Genre":"Value"},"notes":["short reason"]}',
            "",
            "Rules:",
            "- English only.",
            "- Never mention Mercari, source listing, scraping, detection, API, or where the information came from.",
            "- Always leave book_count null. Book count and shipping weight are decided by rules and free reference lookup, not by AI enrichment.",
            "- Description notes must be factual buyer-facing details about condition, included volumes, missing items, shrink-wrap scope, first editions, sun fading, stains, scratches, or unread/new condition.",
            "- Do not include price, payment, shipping method, seller's purchase reason, seller greeting text, or marketplace boilerplate.",
            "- If shrink wrap applies only to specific volumes, state the exact volumes.",
            "- If evidence is weak, omit the field.",
            "- Use only these Specifics columns: " + allowed_columns,
            "- Specifics values must be concise eBay-safe English values.",
            "- Max 5 description notes. Max 12 specifics.",
            "",
            f"Detected book count: {book_count or 'unknown'}",
            "Title:",
            truncate_text(title, 800),
            "",
            "Product description:",
            truncate_text(description, 3500),
            "",
            "Product detail text:",
            truncate_text(details_text, 2500),
        ]
    )


def extract_json_object(text: str) -> str:
    source = str(text or "").strip()
    source = re.sub(r"^```(?:json)?\s*", "", source, flags=re.I)
    source = re.sub(r"\s*```$", "", source)
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", source):
        try:
            _, end = decoder.raw_decode(source[match.start() :])
            return source[match.start() : match.start() + end]
        except Exception:
            continue
    return source


def clean_ai_description_note(value: object) -> str:
    note = clean_text(value)
    if not note or contains_japanese_text(note):
        return ""
    if re.search(r"\b(?:mercari|source listing|scrap(?:e|ing)|detected|api|csv)\b", note, flags=re.I):
        return ""
    if len(note) > 220:
        note = note[:219].rstrip(" ,.;") + "."
    if note and not note.endswith((".", "!", "?")):
        note += "."
    return note


def clean_ai_specific_value(value: object) -> str:
    text = clean_text(value)
    if not text or contains_japanese_text(text):
        return ""
    if text.lower() in {"unknown", "n/a", "na", "none", "null", "not sure"}:
        return ""
    if re.search(r"\b(?:mercari|source listing|scrap(?:e|ing)|detected|api|csv)\b", text, flags=re.I):
        return ""
    if not re.search(r"[A-Za-z0-9]", text):
        return ""
    return truncate_text(text, 120)


def parse_ai_enrichment_payload(text: str, provider: str, model: str, candidate_columns: Iterable[str]) -> AIEnrichment:
    allowed = set(get_specific_columns(candidate_columns, include_defaults=True))
    try:
        payload = json.loads(extract_json_object(text))
    except Exception as error:
        return AIEnrichment(provider=provider, model=model, status=f"parse error: {error}")

    book_count: Optional[int] = None
    book_count_evidence = ""
    if isinstance(payload, dict):
        try:
            raw_book_count = payload.get("book_count")
            if raw_book_count not in (None, "", "null"):
                parsed_count = int(float(str(raw_book_count).strip()))
                if 1 <= parsed_count <= 300:
                    book_count = parsed_count
                    book_count_evidence = clean_text(payload.get("book_count_evidence", "")) or "AI count suggestion"
        except Exception:
            book_count = None
            book_count_evidence = ""

    description_notes: list[str] = []
    raw_description_notes = payload.get("description_notes", []) if isinstance(payload, dict) else []
    for raw_note in raw_description_notes:
        note = clean_ai_description_note(raw_note)
        if note and note not in description_notes:
            description_notes.append(note)
        if len(description_notes) >= 5:
            break

    specifics: dict[str, str] = {}
    raw_specifics = payload.get("specifics", {}) if isinstance(payload, dict) else {}
    if isinstance(raw_specifics, dict):
        for key, raw_value in raw_specifics.items():
            column = str(key or "").strip()
            value = clean_ai_specific_value(raw_value)
            if column in allowed and value:
                specifics[column] = value
            if len(specifics) >= 12:
                break

    notes: list[str] = []
    raw_notes = payload.get("notes", []) if isinstance(payload, dict) else []
    if isinstance(raw_notes, list):
        for raw_note in raw_notes[:6]:
            note = clean_text(raw_note)
            if note and not contains_japanese_text(note):
                notes.append(truncate_text(note, 180))

    return AIEnrichment(
        provider=provider,
        model=model,
        status="ok",
        book_count=book_count,
        book_count_evidence=book_count_evidence,
        description_notes=description_notes,
        specifics=specifics,
        notes=notes,
    )


def parse_openai_response_text(payload: dict) -> str:
    if payload.get("output_text"):
        return str(payload.get("output_text") or "")
    parts: list[str] = []
    for item in payload.get("output", []) or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []) or []:
            if isinstance(content, dict) and content.get("text"):
                parts.append(str(content.get("text")))
    return "\n".join(parts)


def parse_gemini_response_text(payload: dict) -> str:
    parts: list[str] = []
    for candidate in payload.get("candidates", []) or []:
        content = candidate.get("content", {}) if isinstance(candidate, dict) else {}
        for part in content.get("parts", []) or []:
            if isinstance(part, dict) and part.get("text"):
                parts.append(str(part.get("text")))
    return "\n".join(parts)


def call_openai_ai_enrichment(api_key: str, model: str, prompt: str) -> str:
    if requests is None:
        raise RuntimeError("requests is not installed")
    response = requests.post(
        "https://api.openai.com/v1/responses",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "input": [
                {
                    "role": "system",
                    "content": "Extract conservative eBay-safe manga listing facts. Return JSON only.",
                },
                {"role": "user", "content": prompt},
            ],
            "max_output_tokens": 900,
        },
        timeout=45,
    )
    response.raise_for_status()
    text = parse_openai_response_text(response.json())
    if not text:
        raise RuntimeError("OpenAI response did not include text")
    return text


def call_gemini_ai_enrichment(api_key: str, model: str, prompt: str) -> str:
    if requests is None:
        raise RuntimeError("requests is not installed")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    response = requests.post(
        url,
        params={"key": api_key},
        headers={"Content-Type": "application/json"},
        json={
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": "Extract conservative eBay-safe manga listing facts. Return JSON only.\n\n"
                            + prompt
                        }
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0,
                "response_mime_type": "application/json",
            },
        },
        timeout=45,
    )
    response.raise_for_status()
    text = parse_gemini_response_text(response.json())
    if not text:
        raise RuntimeError("Gemini response did not include text")
    return text


def enrich_listing_with_ai(
    *,
    config: ProcessingConfig,
    title: str,
    description: str,
    details_text: str,
    candidate_columns: Iterable[str],
    book_count: Optional[int],
) -> AIEnrichment:
    if not config.enable_ai_enrichment:
        return AIEnrichment(status="disabled")
    provider = normalize_key(config.ai_provider or DEFAULT_AI_PROVIDER)
    model = clean_text(config.ai_model) or (DEFAULT_GEMINI_MODEL if provider == "gemini" else DEFAULT_OPENAI_MODEL)
    api_key = str(config.ai_api_key or "").strip()
    if not api_key:
        return AIEnrichment(provider=provider, model=model, status="missing API key")
    prompt = build_ai_enrichment_prompt(
        title=title,
        description=description,
        details_text=details_text,
        candidate_columns=candidate_columns,
        book_count=book_count,
    )
    try:
        if provider == "openai":
            response_text = call_openai_ai_enrichment(api_key, model, prompt)
        else:
            provider = "gemini"
            response_text = call_gemini_ai_enrichment(api_key, model, prompt)
        return parse_ai_enrichment_payload(response_text, provider, model, candidate_columns)
    except Exception as error:
        return AIEnrichment(provider=provider, model=model, status=format_ai_error_status(provider, error))


def merge_ai_specifics(specifics: SpecificsInference, ai: AIEnrichment, candidate_columns: Iterable[str]) -> None:
    allowed = set(get_specific_columns(candidate_columns, include_defaults=True))
    if ai.status != "ok":
        if ai.status not in {"disabled"}:
            specifics.notes.append(f"AI enrichment {ai.status}")
        return
    for column, value in ai.specifics.items():
        if column in allowed and value:
            specifics.values[column] = value
            specifics.notes.append(f"{column}={value} (AI {ai.provider}/{ai.model})")
    for note in ai.notes:
        specifics.notes.append(f"AI note: {note}")


def append_unique_buyer_notes(base_notes: list[str], extra_notes: Iterable[str]) -> list[str]:
    result = list(base_notes)
    normalized = {normalize_key(note) for note in result}
    for note in extra_notes:
        cleaned = clean_ai_description_note(note)
        key = normalize_key(cleaned)
        if cleaned and key not in normalized:
            result.append(cleaned)
            normalized.add(key)
    return result


def infer_features(text: str, book_count: Optional[int], evidence: str) -> str:
    features: list[str] = []

    def add(value: str) -> None:
        if value and value not in features:
            features.append(value)

    if book_count and book_count > 1:
        add("Set")
    if re.search(r"全巻|完結|complete|completed|full set|all volumes", f"{text}\n{evidence}", flags=re.I):
        add("Complete Series")
    if re.search(r"初版|first edition", text, flags=re.I):
        add("First Edition")
    if re.search(r"限定|limited edition", text, flags=re.I):
        add("Limited Edition")
    if re.search(r"collector'?s edition", text, flags=re.I):
        add("Collector's Edition")
    if re.search(r"full color|フルカラー", text, flags=re.I):
        add("Full Color")
    if re.search(r"シュリンク|shrink wrap|shrinkwrapped|sealed", text, flags=re.I):
        add("Shrink Wrapped")
    if re.search(r"帯付き|帯つき|帯あり", text, flags=re.I):
        add("Obi Included")
    if looks_japanese_manga(text):
        add("Illustrated")
    return "; ".join(features)


def infer_volume_range(text: str) -> str:
    source = normalize_count_text(text)
    patterns = [
        r"(?<!\d)(\d{1,3})\s*(?:-|~|から)\s*(\d{1,3})\s*(?:巻|卷)",
        r"\b(?:vol(?:ume)?s?\.?)\s*(\d{1,3})\s*(?:-|~|to|through)\s*(\d{1,3})\b",
        r"\b(\d{1,3})\s*(?:-|~|to|through)\s*(\d{1,3})\s*(?:vol(?:ume)?s?|books?)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, source, flags=re.I)
        if match:
            start, end = int(match.group(1)), int(match.group(2))
            if 1 <= start <= end <= 300:
                return f"{start}-{end}"
    return ""


def infer_edition(text: str) -> str:
    if re.search(r"collector'?s edition", text, flags=re.I):
        return "Collector's Edition"
    if re.search(r"full color|フルカラー", text, flags=re.I):
        return "Full Color Edition"
    if re.search(r"限定|limited edition", text, flags=re.I):
        return "Limited Edition"
    if re.search(r"初版|first edition", text, flags=re.I):
        return "First Edition"
    return ""


def infer_style(text: str) -> str:
    if re.search(r"full color|フルカラー", text, flags=re.I):
        return "Color"
    if looks_japanese_manga(text):
        return "Black & White"
    return ""


def infer_intended_audience(genre: str) -> str:
    genre_text = str(genre or "")
    if re.search(r"\b(?:Seinen|Josei|Boys'? Love)\b", genre_text, flags=re.I):
        return "Adults"
    if re.search(r"\b(?:Shonen|Shojo)\b", genre_text, flags=re.I):
        return "Young Adults"
    return ""


SOURCE_CONDITION_GRADE_MAP = [
    (r"\b(?:brand\s*new|new[,\s-]*unused|new\s*/\s*unused|unopened|unread|sealed|shrink\s*wrap|shrinkwrapped)\b", "Near Mint", "source condition: new/unread/unopened"),
    (r"\bmint\s*condition\b", "Mint", "source condition: mint condition"),
    (r"\bnear\s*mint\b|\blike\s*new\b|\blike\s*condition\b", "Near Mint", "source condition: like new/near mint"),
    (r"\bexcellent\s*condition\b|\bvery\s*good\s*condition\b", "Very Good", "source condition: excellent/very good condition"),
    (r"\bgood\s*condition\b", "Good", "source condition: good condition"),
    (r"\bacceptable\s*condition\b|\bpoor\s*condition\b", "Acceptable", "source condition: acceptable/poor condition"),
    (r"未使用に近い|ほぼ新品", "Near Mint", "Mercari/source condition: near unused"),
    (r"新品[、,]?\s*未使用|新品未使用|未開封", "Mint", "new/unused"),
    (r"目立った傷や汚れなし|目立つ傷や汚れなし|美品", "Very Good", "source condition: no noticeable damage/clean condition"),
    (r"やや傷や汚れあり", "Good", "source condition: some scratches or stains"),
    (r"傷や汚れあり", "Acceptable", "source condition: scratches or stains"),
    (r"全体的に状態が悪い", "Poor", "source condition: poor overall condition"),
]


def infer_condition_grade(text: str) -> tuple[str, str]:
    for pattern, grade, evidence in SOURCE_CONDITION_GRADE_MAP:
        if re.search(pattern, text, flags=re.I):
            return grade, evidence
    return "", ""


def is_generic_marketplace_description(text: object) -> bool:
    source = str(text or "")
    return bool(
        re.search(r"メルカリでお得に通販|フリマサービス|支払いはクレジットカード|品物が届いてから出品者に入金", source)
    )


def clean_source_listing_description(text: object) -> str:
    description = clean_text(text)
    if is_generic_marketplace_description(description):
        return ""
    return description


def is_ebay_template_description(text: object) -> bool:
    source = str(text or "")
    return bool(
        re.search(
            r"<!\[CDATA\[|comic-ficp-autofill|International Buyers|Please review photos|"
            r"max-width:720px|font-family:Arial|shipping|condition",
            source,
            flags=re.I,
        )
        and re.search(r"<(?:div|p|ul|li|span|style)\b", source, flags=re.I)
    )


def build_condition_evidence_text(
    *,
    title: str,
    listing_description: str = "",
    listing_details_text: str = "",
    csv_description: str = "",
) -> str:
    parts = [title, listing_details_text]
    if listing_description and not is_generic_marketplace_description(listing_description):
        parts.append(listing_description)
    if csv_description and not is_ebay_template_description(csv_description):
        parts.append(csv_description)
    return "\n".join(part for part in parts if part)


def infer_publication_year(text: str) -> str:
    patterns = [
        r"(?:Publication Year|Published|発売日|発行年|出版年)\s*[:：]?\s*(19\d{2}|20\d{2})",
        r"(19\d{2}|20\d{2})\s*年\s*(?:発売|発行|出版)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            return match.group(1)
    return ""


def infer_era(publication_year: str, text: str) -> str:
    year = int(publication_year) if str(publication_year).isdigit() else None
    if year is not None:
        if year >= 1992:
            return "Modern Age (1992-Now)"
        if 1984 <= year <= 1991:
            return "Copper Age (1984-1991)"
        if 1970 <= year <= 1983:
            return "Bronze Age (1970-1983)"
    if re.search(r"modern|現代", text, flags=re.I):
        return "Modern Age (1992-Now)"
    return ""


def infer_isbn(text: str) -> str:
    match = re.search(r"\b(?:ISBN(?:-1[03])?\s*[:：]?\s*)?((?:97[89][-\s]?)?\d[-\s]?\d{2,5}[-\s]?\d{2,7}[-\s]?\d{1,7}[-\s]?[\dX])\b", text, flags=re.I)
    if not match:
        return ""
    isbn = re.sub(r"[-\s]", "", match.group(1)).upper()
    return isbn if len(isbn) in {10, 13} else ""


def build_reference_query(title: str, details_text: str, series_title: str) -> str:
    if series_title and is_english_specific_value(series_title):
        return series_title
    known = infer_known_alias(f"{title}\n{details_text}", SERIES_ALIASES)
    if known:
        return known
    cleaned = infer_series_title(title, details_text)
    return cleaned if is_english_specific_value(cleaned) else ""


@lru_cache(maxsize=128)
def wikidata_reference_lookup(query: str) -> dict[str, object]:
    query = clean_text(query)
    if not query or requests is None:
        return {"status": "reference lookup unavailable", "values": {}}
    headers = {"User-Agent": "comic-ficp-streamlit-app/1.0 (local CSV enrichment)"}
    try:
        search_response = requests.get(
            "https://www.wikidata.org/w/api.php",
            params={
                "action": "wbsearchentities",
                "format": "json",
                "language": "en",
                "type": "item",
                "limit": 5,
                "search": f"{query} manga",
            },
            headers=headers,
            timeout=6,
        )
        search_response.raise_for_status()
        search_items = search_response.json().get("search", [])
    except Exception as error:
        return {"status": f"reference lookup failed: {error}", "values": {}}

    selected = {}
    for item in search_items:
        description = str(item.get("description", "")).lower()
        label = str(item.get("label", "")).lower()
        if "manga" in description or "comic" in description or query.lower() in label:
            selected = item
            break
    if not selected and search_items:
        selected = search_items[0]
    entity_id = selected.get("id", "")
    if not entity_id:
        return {"status": "reference lookup found no matching item", "values": {}}

    try:
        entity_response = requests.get(
            "https://www.wikidata.org/w/api.php",
            params={
                "action": "wbgetentities",
                "format": "json",
                "ids": entity_id,
                "props": "claims|labels",
                "languages": "en",
            },
            headers=headers,
            timeout=6,
        )
        entity_response.raise_for_status()
        entity = entity_response.json().get("entities", {}).get(entity_id, {})
    except Exception as error:
        return {"status": f"reference entity lookup failed: {error}", "values": {}}

    claims = entity.get("claims", {}) if isinstance(entity, dict) else {}
    label_ids: set[str] = set()
    for property_id in ("P50", "P123", "P136", "P674", "P407", "P495"):
        for claim in claims.get(property_id, []):
            value_id = wikidata_claim_entity_id(claim)
            if value_id:
                label_ids.add(value_id)
    labels = fetch_wikidata_labels(tuple(sorted(label_ids)))

    def claim_labels(property_id: str, limit: int = 5) -> list[str]:
        values: list[str] = []
        for claim in claims.get(property_id, []):
            value_id = wikidata_claim_entity_id(claim)
            label = labels.get(value_id, "")
            if label and label not in values:
                values.append(label)
            if len(values) >= limit:
                break
        return values

    year = ""
    for claim in claims.get("P577", []):
        time_value = wikidata_claim_time(claim)
        year_match = re.search(r"([12]\d{3})", time_value)
        if year_match:
            year = year_match.group(1)
            break

    values: dict[str, str] = {}
    authors = claim_labels("P50", 2)
    publishers = claim_labels("P123", 2)
    genres = claim_labels("P136", 4)
    characters = claim_labels("P674", 5)
    languages = claim_labels("P407", 2)
    countries = claim_labels("P495", 2)
    if authors:
        values["author"] = "; ".join(authors)
    if publishers:
        values["publisher"] = publishers[0]
    if genres:
        values["genre"] = normalize_reference_genre(genres)
    if characters:
        values["characters"] = "; ".join(characters)
    if any(label.lower() == "japanese" for label in languages):
        values["language"] = "Japanese"
    if any(label.lower() == "japan" for label in countries):
        values["country"] = "Japan"
    if year:
        values["publication_year"] = year

    label = entity.get("labels", {}).get("en", {}).get("value", query)
    return {"status": f"Wikidata {entity_id}: {label}", "values": values}


def wikidata_claim_entity_id(claim: dict) -> str:
    try:
        value = claim["mainsnak"]["datavalue"]["value"]
    except Exception:
        return ""
    if isinstance(value, dict) and value.get("entity-type") == "item":
        numeric_id = value.get("numeric-id")
        return f"Q{numeric_id}" if numeric_id else ""
    return ""


def wikidata_claim_time(claim: dict) -> str:
    try:
        value = claim["mainsnak"]["datavalue"]["value"]
    except Exception:
        return ""
    return str(value.get("time", "")) if isinstance(value, dict) else ""


@lru_cache(maxsize=256)
def fetch_wikidata_labels(entity_ids: tuple[str, ...]) -> dict[str, str]:
    ids = [entity_id for entity_id in entity_ids if entity_id]
    if not ids or requests is None:
        return {}
    try:
        response = requests.get(
            "https://www.wikidata.org/w/api.php",
            params={
                "action": "wbgetentities",
                "format": "json",
                "ids": "|".join(ids),
                "props": "labels",
                "languages": "en",
            },
            headers={"User-Agent": "comic-ficp-streamlit-app/1.0 (local CSV enrichment)"},
            timeout=6,
        )
        response.raise_for_status()
        entities = response.json().get("entities", {})
    except Exception:
        return {}
    return {
        entity_id: data.get("labels", {}).get("en", {}).get("value", "")
        for entity_id, data in entities.items()
        if isinstance(data, dict)
    }


def normalize_reference_genre(genres: list[str]) -> str:
    joined = " ".join(genres)
    values: list[str] = []

    def add(value: str) -> None:
        if value and value not in values:
            values.append(value)

    genre_rules = [
        ("Action", r"\baction\b"),
        ("Adventure", r"\badventure\b"),
        ("Comedy", r"\bcomedy\b|comic"),
        ("Drama", r"\bdrama\b"),
        ("Fantasy", r"\bfantasy\b"),
        ("Romance", r"\bromance\b"),
        ("Science Fiction", r"science fiction|\bsci-fi\b"),
        ("Slice of Life", r"slice of life"),
        ("Sports", r"\bsports?\b"),
        ("Horror", r"\bhorror\b"),
        ("Mystery", r"\bmystery\b"),
        ("Spy Fiction", r"\bspy\b|espionage"),
        ("Shonen", r"sh[oō]nen"),
        ("Shojo", r"sh[oō]jo"),
        ("Seinen", r"\bseinen\b"),
        ("Josei", r"\bjosei\b"),
    ]
    for value, pattern in genre_rules:
        if re.search(pattern, joined, flags=re.I):
            add(value)
    if values:
        return ", ".join(values[:5])
    cleaned = [genre.replace(" manga", "").title() for genre in genres if genre]
    return ", ".join(cleaned[:3])


def infer_specifics_with_notes(
    title: str,
    details_text: str,
    candidate_columns: Optional[Iterable[str]] = None,
    book_count: Optional[int] = None,
    weight_kg: Optional[float] = None,
    book_count_evidence: str = "",
    enable_reference_lookup: bool = False,
    condition_text: str = "",
) -> SpecificsInference:
    specific_columns = get_specific_columns(candidate_columns if candidate_columns is not None else DEFAULT_SPECIFIC_COLUMNS, include_defaults=True)
    text = f"{title}\n{details_text}"
    publisher = infer_publisher(text)
    author = infer_author(text)
    series_title = infer_series_title(title, details_text)
    series_reference = SERIES_REFERENCE_DATA.get(series_title, {})
    reference_status = ""
    if enable_reference_lookup:
        reference_query = build_reference_query(title, details_text, series_title)
        reference_result = wikidata_reference_lookup(reference_query) if reference_query else {"status": "reference lookup skipped: no reliable series query", "values": {}}
        reference_values = reference_result.get("values", {}) if isinstance(reference_result, dict) else {}
        reference_status = str(reference_result.get("status", "")) if isinstance(reference_result, dict) else ""
    else:
        reference_values = {}

    publisher = publisher or str(series_reference.get("publisher", "")) or str(reference_values.get("publisher", ""))
    author = author or str(series_reference.get("author", "")) or str(reference_values.get("author", ""))
    genre = str(series_reference.get("genre", "")) or infer_genre(text) or str(reference_values.get("genre", ""))
    language = "Japanese" if looks_japanese_manga(text) or publisher else ""
    language = language or str(reference_values.get("language", ""))
    country = str(reference_values.get("country", "")) or "Japan"
    characters = str(series_reference.get("characters", "")) or str(reference_values.get("characters", ""))
    features = infer_features(text, book_count, book_count_evidence)
    edition = infer_edition(text)
    style = infer_style(text)
    intended_audience = infer_intended_audience(genre)
    publication_year = infer_publication_year(text) or str(series_reference.get("publication_year", "")) or str(reference_values.get("publication_year", ""))
    era = infer_era(publication_year, text)
    isbn = infer_isbn(text)
    signed = "Yes" if re.search(r"サイン|signed|autograph", text, flags=re.I) else "No"
    volume_range = infer_volume_range(text)
    condition_grade, condition_grade_evidence = infer_condition_grade(condition_text or text)

    specifics: dict[str, str] = {}
    notes: list[str] = []

    add_specific_value(specifics, notes, specific_columns, ["Format", "Book Format"], "Paperback", "manga volume default")
    add_specific_value(specifics, notes, specific_columns, ["Type"], "Manga", "manga set workflow")
    add_specific_value(
        specifics,
        notes,
        specific_columns,
        ["Country/Region of Manufacture", "Country of Manufacture", "Country"],
        country,
        "source marketplace/reference evidence",
    )
    add_specific_value(specifics, notes, specific_columns, ["Language"], language, "Japanese manga/source text evidence")
    add_specific_value(specifics, notes, specific_columns, ["Original Language", "Original Language of Publication"], "Japanese", "Japanese manga workflow")
    add_specific_value(specifics, notes, specific_columns, ["Narrative Type"], "Fiction", "manga set default")
    add_specific_value(specifics, notes, specific_columns, ["Tradition"], "Manga", "manga set workflow")
    add_specific_value(specifics, notes, specific_columns, ["Topic"], "Manga", "manga set workflow")
    add_specific_value(specifics, notes, specific_columns, ["Unit of Sale"], "Comic Book Lot", "multi-volume set workflow")
    add_specific_value(specifics, notes, specific_columns, ["Unit Type"], DEFAULT_EXPORT_UNIT_TYPE, "unit price display label")
    add_specific_value(specifics, notes, specific_columns, ["Signed"], signed, "signature evidence/default")
    add_specific_value(specifics, notes, specific_columns, ["Personalized", "Personalize"], "No", "no personalization evidence")
    add_specific_value(specifics, notes, specific_columns, ["Inscribed"], "No", "no inscription evidence")
    add_specific_value(specifics, notes, specific_columns, ["Ex Libris"], "No", "no ex-libris evidence")
    add_specific_value(specifics, notes, specific_columns, ["MPN"], "Does Not Apply", "book set has no manufacturer part number")
    add_specific_value(specifics, notes, specific_columns, ["Material"], "Paper", "book material default")
    add_specific_value(specifics, notes, specific_columns, ["California Prop 65 Warning"], "Not Applicable", "paper book set default")
    add_specific_value(specifics, notes, specific_columns, ["Convention/Event"], "Not Applicable", "no convention/event evidence")
    add_specific_value(specifics, notes, specific_columns, ["Custom Bundle"], "Yes" if book_count and book_count > 1 else "No", "detected set count")
    add_specific_value(specifics, notes, specific_columns, ["Autograph Authentication"], "Not Applicable" if signed == "No" else "", "not signed")
    add_specific_value(specifics, notes, specific_columns, ["Autograph Authentication Number"], "Not Applicable" if signed == "No" else "", "not signed")
    add_specific_value(specifics, notes, specific_columns, ["Certification Number"], "Not Applicable", "no certification evidence")
    add_specific_value(specifics, notes, specific_columns, ["Professional Grader"], "Not Professionally Graded", "ungraded manga set workflow")

    if publisher:
        add_specific_value(specifics, notes, specific_columns, ["Publisher"], publisher, "publisher evidence found")
        add_specific_value(specifics, notes, specific_columns, ["Brand"], publisher, "publisher evidence found")
    else:
        add_specific_value(specifics, notes, specific_columns, ["Brand"], "No Brand", "publisher evidence was weak")
        notes.append("C:Publisher not filled (publisher evidence was weak)")
    if author:
        add_specific_value(specifics, notes, specific_columns, ["Author", "Artist/Writer", "Writer", "Creator"], author, "author evidence found")
    else:
        notes.append("C:Author not filled (author evidence was weak)")
    if series_title:
        add_specific_value(
            specifics,
            notes,
            specific_columns,
            ["Series", "Book Series", "Series Title", "Book Title", "Story Title", "Title"],
            series_title,
            "series/title evidence found",
        )
        add_specific_value(specifics, notes, specific_columns, ["Universe"], series_title, "series/title evidence found")
    else:
        notes.append("C:Series/C:Book Title not filled (title evidence was weak)")
    if genre:
        add_specific_value(specifics, notes, specific_columns, ["Genre"], genre, "genre keyword evidence")
    else:
        notes.append("C:Genre not filled (genre evidence was weak)")
    if condition_grade:
        add_specific_value(
            specifics,
            notes,
            specific_columns,
            ["Grade", "Condition Grade"],
            condition_grade,
            condition_grade_evidence,
        )
    add_specific_value(specifics, notes, specific_columns, ["Intended Audience"], intended_audience, "genre audience inference")
    add_specific_value(specifics, notes, specific_columns, ["Features"], features, "manga set feature inference")
    add_specific_value(specifics, notes, specific_columns, ["Edition"], edition, "edition keyword evidence")
    add_specific_value(specifics, notes, specific_columns, ["Style"], style, "manga print style inference")
    add_specific_value(specifics, notes, specific_columns, ["Character"], characters or ("Various" if book_count and book_count > 1 else ""), "series/reference evidence")
    if book_count:
        add_specific_value(specifics, notes, specific_columns, ["Number of Books", "Number of Items", "Unit Quantity"], str(book_count), "detected book count")
        add_specific_value(specifics, notes, specific_columns, ["Issue Number", "Volume"], volume_range or "Various", "detected volume range/set")
    if weight_kg:
        add_specific_value(specifics, notes, specific_columns, ["Item Weight", "Weight"], f"{weight_kg:.2f} kg", "estimated manga set weight")
    if publication_year:
        add_specific_value(specifics, notes, specific_columns, ["Publication Year"], publication_year, "publication year evidence")
    add_specific_value(specifics, notes, specific_columns, ["Era"], era, "publication year inference")
    if str(publication_year).isdigit():
        add_specific_value(specifics, notes, specific_columns, ["Vintage"], "Yes" if int(publication_year) < 2000 else "No", "publication year inference")
    if isbn:
        add_specific_value(specifics, notes, specific_columns, ["ISBN", "ISBN-10", "ISBN-13"], isbn, "ISBN evidence found")
    elif book_count and book_count > 1:
        add_specific_value(specifics, notes, specific_columns, ["ISBN", "ISBN-10", "ISBN-13"], "Does Not Apply", "multi-volume set has no single ISBN")
    if reference_status:
        notes.append(reference_status)

    return SpecificsInference(
        values={key: value for key, value in specifics.items() if value},
        notes=notes,
    )


def infer_specifics(title: str, details_text: str) -> dict[str, str]:
    return infer_specifics_with_notes(title, details_text).values


def infer_author(text: str) -> str:
    known_author = infer_known_alias(text, AUTHOR_ALIASES)
    if known_author:
        return known_author
    labeled = infer_labeled_value(text, ["著者", "作者", "Author", "Creator"])
    if labeled:
        return labeled if is_english_specific_value(labeled) else ""
    match = re.search(
        r"\bby\s+([A-Z][A-Za-z][A-Za-z .'\-]{1,70}?)(?=(?:\s+(?:Publisher|Author|Language|Description)\s*[:：])|$)",
        text,
        flags=re.I,
    )
    value = clean_text(match.group(1))[:80] if match else ""
    return value if is_english_specific_value(value) else ""


def infer_known_alias(text: str, alias_map: dict[str, list[str]]) -> str:
    source = str(text or "")
    for english_value, aliases in alias_map.items():
        if any(re.search(re.escape(alias), source, flags=re.I) for alias in aliases):
            return english_value
    return ""


def infer_series_title(title: str, details_text: str = "") -> str:
    known_series = infer_known_alias(f"{title}\n{details_text}", SERIES_ALIASES)
    if known_series:
        return known_series

    source = clean_text(title)
    if not source:
        return ""
    cleaned = source
    patterns = [
        r"【[^】]*】",
        r"\[[^\]]*\]",
        r"\b(?:vol(?:ume)?s?\.?)\s*\d+\s*(?:-|~|to|through)\s*\d+\b",
        r"\b\d+\s*(?:-|~|to|through)\s*\d+\s*(?:vol(?:ume)?s?|books?)\b",
        r"\b(?:vol(?:ume)?s?\.?)\s*\d+\b",
        r"\bby\s+[A-Z][A-Za-z .'\-]{1,70}$",
        r"\s+by\s+メルカリ\b",
        r"\b\d+\s*(?:book|volume|vol)\s*(?:complete\s*)?set\b",
        r"\b(?:complete|completed|full|all)\s*(?:manga|comic)?\s*set\b",
        r"\b(?:manga|comic|comics|set|lot|bundle)\b",
        r"\b(?:excellent|good|very good|used|new|sealed|shrink wrap|with shrink wrap)\s*(?:condition)?\b",
        r"\b(?:collector's edition|full color edition)\b",
        r"美品|番外編|おまけ|特典|限定|初版|新品|未使用|中古|全巻|完結|少女漫画|少年漫画|青年漫画|女性漫画|メルカリ",
        r"(?:全|完結)\s*\d{1,3}\s*(?:巻|卷|冊|册)",
        r"\d{1,3}\s*(?:巻|卷|冊|册)\s*(?:セット|まとめ|全巻)?",
    ]
    for pattern in patterns:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.I)
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = cleaned.strip(" -_/.,:;()[]{}｜|")
    if contains_japanese_text(cleaned):
        return ""
    return cleaned[:120] if len(cleaned) >= 2 and is_english_specific_value(cleaned) else ""


def infer_genre(text: str) -> str:
    genre_patterns = [
        ("Shonen", r"少年|shonen|shounen|jump|ジャンプ|マガジン|サンデー"),
        ("Shojo", r"少女|shojo|shoujo|りぼん|マーガレット|花とゆめ"),
        ("Seinen", r"青年|seinen|ヤング|ビッグコミック|モーニング"),
        ("Josei", r"女性|josei|\bkiss\b|be love|フィールヤング"),
        ("Boys' Love", r"boys'? love|ボーイズラブ|\bBL\b"),
        ("Sports", r"\bsports?\b|soccer|football"),
        ("Romance", r"\bromance\b|romantic"),
        ("Comedy", r"\bcomedy\b|gag manga"),
        ("Horror", r"\bhorror\b|ghoul|vampire"),
        ("Historical", r"\bhistorical\b|history"),
    ]
    for genre, pattern in genre_patterns:
        if re.search(pattern, text, flags=re.I):
            return genre
    return ""


def infer_publisher(text: str) -> str:
    labeled = infer_labeled_value(text, ["出版社", "Publisher"])
    if labeled:
        for publisher, aliases in PUBLISHER_ALIASES.items():
            if any(re.search(re.escape(alias), labeled, flags=re.I) for alias in aliases):
                return publisher
        return labeled if is_english_specific_value(labeled) else ""
    for publisher, aliases in PUBLISHER_ALIASES.items():
        if any(re.search(re.escape(alias), text, flags=re.I) for alias in aliases):
            return publisher
    return ""


def infer_labeled_value(text: str, labels: list[str]) -> str:
    common_stop_labels = [
        "著者",
        "作者",
        "Author",
        "Creator",
        "出版社",
        "Publisher",
        "言語",
        "Language",
        "シリーズ",
        "Series",
        "Book Title",
        "タイトル",
        "Title",
        "状態",
        "Condition",
    ]
    stop_pattern = "|".join(re.escape(label) for label in sorted(set(common_stop_labels + labels), key=len, reverse=True))
    for label in labels:
        pattern = rf"{re.escape(label)}\s*[:：]\s*(.+?)(?=(?:\s+(?:{stop_pattern})\s*[:：])|[\n\r/|｜,，;；]|$)"
        match = re.search(pattern, text, flags=re.I)
        if match:
            value = clean_text(match.group(1))
            return value[:80]
    return ""


def looks_japanese_manga(text: str) -> bool:
    return bool(
        re.search(r"[ぁ-んァ-ン一-龥]", text)
        or re.search(r"\b(japanese|manga|comic)\b", text, flags=re.I)
    )


def apply_item_specifics(row: pd.Series, specifics: dict[str, str]) -> pd.Series:
    updated, _ = apply_item_specifics_with_report(row, specifics)
    return updated


def clear_non_english_specific_values(row: pd.Series, specific_columns: Optional[Iterable[str]] = None) -> tuple[pd.Series, list[str]]:
    updated = row.copy()
    notes: list[str] = []
    skip_keys = {
        "language",
        "originallanguage",
        "country",
        "countryregionofmanufacture",
        "countryofmanufacture",
    }
    for key in specific_columns or get_specific_columns(updated.index, include_defaults=False):
        current = get_row_value(updated, key)
        if (
            current
            and not is_blank(current)
            and contains_japanese_text(current)
            and normalized_specific_name(key) not in skip_keys
        ):
            updated[key] = ""
            notes.append(f"cleared {key} because it contained non-English text")
    return updated, notes


def limit_item_specific_value(value: object, max_chars: int = EBAY_ITEM_SPECIFIC_VALUE_MAX_CHARS) -> tuple[str, bool]:
    text = clean_text(value)
    if len(text) <= max_chars:
        return text, False

    if ";" in text:
        kept: list[str] = []
        for part in [clean_text(item) for item in text.split(";")]:
            if not part:
                continue
            candidate = "; ".join(kept + [part])
            if len(candidate) <= max_chars:
                kept.append(part)
                continue
            if kept:
                return "; ".join(kept), True
            break

    shortened = text[:max_chars].rstrip(" ,.;")
    return shortened, True


def limit_item_specific_values(
    row: pd.Series,
    specific_columns: Optional[Iterable[str]] = None,
) -> tuple[pd.Series, list[str]]:
    updated = row.copy()
    notes: list[str] = []
    columns = list(specific_columns or get_specific_columns(updated.index, include_defaults=False))
    for key in columns:
        if not str(key).startswith("C:"):
            continue
        current = get_row_value(updated, key)
        if not current:
            continue
        limited, changed = limit_item_specific_value(current)
        if changed:
            updated[key] = limited
            notes.append(f"shortened {key} to {EBAY_ITEM_SPECIFIC_VALUE_MAX_CHARS} characters or less")
    return updated, notes


def apply_item_specifics_with_report(
    row: pd.Series,
    specifics: dict[str, str],
    target_columns: Optional[Iterable[str]] = None,
) -> tuple[pd.Series, list[str]]:
    updated = row.copy()
    notes: list[str] = []
    allowed = set(target_columns) if target_columns is not None else None
    for key, value in specifics.items():
        if allowed is not None and key not in allowed:
            continue
        if key not in updated.index:
            updated[key] = ""
        if is_replaceable_specific_value(key, updated.get(key, "")):
            limited_value, shortened = limit_item_specific_value(value) if str(key).startswith("C:") else (str(value or ""), False)
            updated[key] = limited_value
            notes.append(f"filled {key}")
            if shortened:
                notes.append(f"shortened {key} to {EBAY_ITEM_SPECIFIC_VALUE_MAX_CHARS} characters or less")
        else:
            notes.append(f"kept existing {key}")
    updated, limit_notes = limit_item_specific_values(updated, target_columns)
    notes.extend(limit_notes)
    return updated, notes


def build_specifics_application_summary(
    original_row: pd.Series,
    updated_row: pd.Series,
    inferred_specifics: dict[str, str],
    specific_columns: Optional[Iterable[str]] = None,
) -> dict[str, dict[str, str]]:
    summary: dict[str, dict[str, str]] = {
        "filled": {},
        "existing": {},
        "not_filled": {},
    }
    for column in specific_columns or get_specific_columns(updated_row.index, include_defaults=True):
        original_value = get_row_value(original_row, column)
        updated_value = get_row_value(updated_row, column)
        inferred_value = inferred_specifics.get(column, "")
        if inferred_value and is_replaceable_specific_value(column, original_value) and updated_value:
            summary["filled"][column] = updated_value
        elif not is_replaceable_specific_value(column, original_value):
            summary["existing"][column] = original_value
        elif inferred_value and updated_value:
            summary["existing"][column] = updated_value
        else:
            summary["not_filled"][column] = ""
    return summary


def format_specifics_field_map(values: dict[str, str]) -> str:
    return "; ".join(f"{key}={value}" if value else key for key, value in values.items())


def parse_specifics_field_map(value: object) -> dict[str, str]:
    result: dict[str, str] = {}
    for part in str(value or "").split(";"):
        text = part.strip()
        if not text:
            continue
        if "=" in text:
            key, field_value = text.split("=", 1)
            result[key.strip()] = field_value.strip()
        else:
            result[text] = ""
    return result


def find_specifics_note_reason(notes_text: object, column: str) -> str:
    notes = str(notes_text or "")
    if not notes or not column:
        return ""
    pattern = rf"{re.escape(column)}=([^;]+?)(?:\s*\(([^;()]+)\))?(?=;|$)"
    match = re.search(pattern, notes)
    if not match:
        return ""
    value = clean_text(match.group(1))
    reason = clean_text(match.group(2))
    if reason:
        return f"{value} / {reason}"
    return value


IMPORTANT_DETAIL_KEYWORDS = re.compile(
    r"状態|傷|キズ|汚れ|スレ|擦れ|ヤケ|焼け|日焼け|黄ばみ|折れ|破れ|"
    r"シミ|濡れ|水濡れ|ヨレ|凹み|へこみ|カバー|ページ|帯|初版|"
    r"レンタル落ち|漫画喫茶|ネットカフェ|書き込み|欠品|抜け|付属|特典|"
    r"新品|未読|未使用|中古|開封|シュリンク|裁断|応募券|切り取り|切取|切り抜き|"
    r"全巻|巻|冊|セット|完結",
    flags=re.I,
)

UNNEEDED_DETAIL_KEYWORDS = re.compile(
    r"定価|購入|買いまし|譲って|譲り受け|もらい|貰い|頂き|いただき|"
    r"プレゼント|出品しま|断捨離|即購入|バラ売り|値下げ|値引き|"
    r"発送|梱包|送料|プロフィール|プロフ|コメント|購入前|専用|取り置き|"
    r"キャンセル|返品|メルカリ便|らくらく|ゆうゆう|匿名配送|"
    r"メルカリ|フリマ|通販|支払い|クレジット|キャリア|コンビニ|ATM|入金|安心",
    flags=re.I,
)

CONDITION_TRANSLATIONS = [
    (r"美品", "Condition: clean/good condition."),
    (r"ほぼ新品|未使用に近い", "Condition: close to unused."),
    (r"新品未読|未読", "Condition: new/unread."),
    (r"新品[、,]?\s*未使用|新品未使用", "Condition: new/unused."),
    (r"目立った傷や汚れなし|目立つ傷や汚れなし", "Condition: no noticeable scratches or stains."),
    (r"やや傷や汚れあり", "Condition: some scratches or stains."),
    (r"傷や汚れあり", "Condition: scratches or stains."),
    (r"全体的に状態が悪い", "Condition: poor overall condition."),
    (r"レンタル落ち", "Former rental copy/copies may be included."),
    (r"漫画喫茶|ネットカフェ", "Former comic cafe/library-use copies may be included."),
    (r"書き込み", "Writing or markings may be present."),
    (r"裁断", "Cut/scanned-copy condition may be present."),
    (r"水濡れ|濡れ", "Water exposure or water damage may be present."),
    (r"破れ", "Tears may be present."),
    (r"折れ", "Creases or folds may be present."),
    (r"シミ|汚れ", "Stains or dirt may be present."),
    (r"ヤケ|焼け|日焼け|黄ばみ", "Page tanning or sun fading may be present."),
    (r"スレ|擦れ|傷|キズ", "Scratches or scuffs may be present."),
    (r"帯付き|帯つき|帯あり", "Obi band is included."),
    (r"帯なし|帯無し", "Obi band is not included."),
    (r"特典付き|特典あり|付属", "Bonus items or extras are included."),
    (r"欠品|抜け", "Some items or details may be missing."),
    (
        r"応募券[^。.!?]{0,40}(切り取り|切取|切り抜き|取り除|なし|無し|ありません)|"
        r"(切り取り済み|切取済み)",
        "Application/coupon ticket has been cut out or removed.",
    ),
    (
        r"シュリンク[^。.!?]{0,30}(付いていません|ついていません|ありません|なし|無し|ない)",
        "Shrink wrap is not included.",
    ),
    (
        r"シュリンク[^。.!?]{0,30}(付き|つき|あり|有り|未開封|付いています|ついています)",
        "Shrink wrap is included.",
    ),
    (r"シュリンク", "Shrink wrap condition should be checked in the photos."),
]


def format_volume_scope_english(sentence: str) -> tuple[str, bool]:
    match = re.search(
        r"((?:\d{1,3}\s*(?:[.,、・･/／&と]|-|－|〜|～|~)\s*)*\d{1,3})\s*(?:巻|卷)",
        sentence,
    )
    if not match:
        return "", False

    raw_scope = match.group(1)
    numbers = re.findall(r"\d{1,3}", raw_scope)
    if not numbers:
        return "", False

    has_range = bool(re.search(r"-|－|〜|～|~", raw_scope)) and len(numbers) >= 2
    if has_range:
        return f"Volumes {numbers[0]}-{numbers[-1]}", True
    if len(numbers) == 1:
        return f"Volume {numbers[0]}", False
    if len(numbers) == 2:
        return f"Volumes {numbers[0]} and {numbers[1]}", True
    return f"Volumes {', '.join(numbers[:-1])}, and {numbers[-1]}", True


def summarize_shrink_wrap_sentence(sentence: str) -> str:
    if "シュリンク" not in sentence:
        return ""

    negative = re.search(r"シュリンク[^。.!?]{0,40}(付いていません|ついていません|ありません|なし|無し|ない)", sentence, flags=re.I)
    positive = re.search(r"シュリンク[^。.!?]{0,40}(付き|つき|あり|有り|未開封|付いています|ついています)", sentence, flags=re.I)
    subject, is_plural = format_volume_scope_english(sentence)

    if negative:
        if subject:
            return f"{subject} {'are' if is_plural else 'is'} not shrink-wrapped."
        return "Shrink wrap is not included."
    if positive:
        if subject:
            return f"{subject} {'are' if is_plural else 'is'} shrink-wrapped."
        if re.search(r"全巻|全ての巻|すべての巻", sentence):
            return "All volumes are shrink-wrapped."
        return "Shrink wrap is mentioned as included. Please review photos to confirm which volume(s) are shrink-wrapped."
    return "Shrink wrap condition should be checked in the photos."


def summarize_first_edition_sentence(sentence: str) -> str:
    if "初版" not in sentence:
        return ""
    if re.search(r"(すべて|全て|全部|全巻)[^。.!?]{0,40}初版|初版[^。.!?]{0,40}(すべて|全て|全部|全巻)", sentence):
        return "All volumes are first editions."

    subject, is_plural = format_volume_scope_english(sentence)
    if subject:
        return f"{subject} {'are' if is_plural else 'is a'} first edition{'s' if is_plural else ''}."
    return "First edition volume(s) may be included."


def summarize_tanning_sentence(sentence: str) -> str:
    if not re.search(r"ヤケ|焼け|日焼け|黄ばみ", sentence):
        return ""
    if re.search(
        r"(ほとんど|ほぼ|あまり)[^。.!?]{0,20}(してません|していません|ありません|ない)|"
        r"(ヤケ|焼け|日焼け|黄ばみ)[^。.!?]{0,20}(なし|無し|ありません|ない|少な)",
        sentence,
    ):
        return "Little to no page tanning or sun fading is mentioned."
    return ""


def extract_buyer_relevant_listing_details(
    listing_description: str,
    listing_details_text: str,
    max_items: int = 5,
) -> list[str]:
    details: list[str] = []
    seen: set[str] = set()
    for sentence in split_detail_sentences(f"{listing_description}\n{listing_details_text}"):
        detail = summarize_relevant_detail_sentence(sentence)
        if not detail:
            continue
        key = normalize_key(detail)
        if key in seen:
            continue
        seen.add(key)
        details.append(detail)
        if len(details) >= max_items:
            break
    return details


def split_detail_sentences(text: str) -> list[str]:
    source = str(text or "")
    source = re.sub(r"<\s*br\s*/?\s*>", "\n", source, flags=re.I)
    source = re.sub(r"</(?:p|li|div|section|h\d)>", "\n", source, flags=re.I)
    source = re.sub(r"<[^>]+>", " ", source)
    source = unescape(source)
    source = source.replace("。", "。\n").replace("！", "！\n").replace("？", "？\n")
    source = re.sub(r"\s*[|｜]\s*", "\n", source)
    parts = re.split(r"[\n\r]+|(?<=[.!?])\s+", source)

    sentences: list[str] = []
    for part in parts:
        sentence = clean_text(part)
        if len(sentence) > 220:
            sentence = sentence[:220].rsplit(" ", 1)[0].strip() or sentence[:220]
        if 4 <= len(sentence) <= 220:
            sentences.append(sentence)
    return sentences


def build_source_detail_preview(listing_description: str, listing_details_text: str, limit: int = 700) -> str:
    candidates: list[str] = []
    seen: set[str] = set()
    skip_pattern = re.compile(
        r"ログイン|会員登録|アプリ|ダウンロード|カテゴリー|カテゴリ|ブランド|商品の状態|"
        r"配送料|配送の方法|発送元|発送まで|購入手続き|コメント|いいね|メルカリ",
        flags=re.I,
    )
    for sentence in split_detail_sentences(f"{listing_description}\n{listing_details_text}"):
        if is_generic_marketplace_description(sentence):
            continue
        if skip_pattern.search(sentence):
            continue
        if len(sentence) < 5:
            continue
        key = normalize_key(sentence)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(sentence)
        if len(" / ".join(candidates)) >= limit:
            break
    return truncate_text(" / ".join(candidates), limit)


def summarize_relevant_detail_sentence(sentence: str) -> str:
    sentence = clean_text(sentence)
    if not sentence or not IMPORTANT_DETAIL_KEYWORDS.search(sentence):
        return ""
    if re.search(r"^https?://|ログイン|会員登録|アプリ|カテゴリ|ブランド|価格|商品の説明$", sentence, flags=re.I):
        return ""

    translated = []
    first_edition_note = summarize_first_edition_sentence(sentence)
    if first_edition_note:
        translated.append(first_edition_note)
    tanning_note = summarize_tanning_sentence(sentence)
    if tanning_note:
        translated.append(tanning_note)
    shrink_wrap_note = summarize_shrink_wrap_sentence(sentence)
    if shrink_wrap_note:
        translated.append(shrink_wrap_note)
    for pattern, message in CONDITION_TRANSLATIONS:
        if shrink_wrap_note and "Shrink wrap" in message:
            continue
        if tanning_note and message == "Page tanning or sun fading may be present.":
            continue
        if re.search(pattern, sentence, flags=re.I) and message not in translated:
            if is_packaging_water_prevention_note(sentence, message):
                continue
            if any("close to unused" in item for item in translated) and message == "Condition: new/unused.":
                continue
            if any("no noticeable scratches or stains" in item for item in translated) and message in {
                "Stains or dirt are mentioned.",
                "Scratches or scuffs are mentioned.",
            }:
                continue
            translated.append(message)

    if translated:
        context = summarize_sentence_context_english(sentence)
        note = " ".join(translated[:2] + context[:2])
        return trim_detail_note(note)

    if UNNEEDED_DETAIL_KEYWORDS.search(sentence):
        return ""

    context = summarize_sentence_context_english(sentence)
    return trim_detail_note(" ".join(context[:2])) if context else ""


def is_packaging_water_prevention_note(sentence: str, message: str) -> bool:
    if message != "Water exposure or water damage may be present.":
        return False
    return bool(re.search(r"水濡れ防止|濡れ防止|防水|OPP|ビニール|梱包|発送", sentence, flags=re.I))


def contains_specific_condition_context(sentence: str) -> bool:
    return bool(re.search(r"\d+\s*(?:巻|冊)|表紙|裏表紙|小口|天|地|ページ|カバー|帯|特典", sentence, flags=re.I))


def summarize_sentence_context_english(sentence: str) -> list[str]:
    context: list[str] = []
    if not re.search(
        r"傷|キズ|汚れ|スレ|擦れ|ヤケ|焼け|日焼け|黄ばみ|折れ|破れ|"
        r"シミ|濡れ|水濡れ|ヨレ|凹み|へこみ|表紙|裏表紙|小口|ページ|"
        r"カバー|帯|特典|書き込み|欠品|抜け|レンタル落ち|裁断",
        sentence,
        flags=re.I,
    ):
        return context

    volume_numbers = []
    for match in re.finditer(r"(\d{1,3})\s*(?:巻|卷)", normalize_count_text(sentence)):
        number = int(match.group(1))
        if number not in volume_numbers and 1 <= number <= 300:
            volume_numbers.append(number)
    if volume_numbers:
        joined = ", ".join(str(number) for number in volume_numbers[:4])
        context.append(f"Volume {joined} may have the noted condition.")

    part_terms = [
        ("表紙", "front cover"),
        ("裏表紙", "back cover"),
        ("小口", "page edges"),
        ("ページ", "pages"),
        ("カバー", "cover"),
        ("帯", "obi band"),
        ("特典", "bonus item/extras"),
    ]
    mentioned_parts = []
    for pattern, english_part in part_terms:
        if re.search(pattern, sentence, flags=re.I) and english_part not in mentioned_parts:
            mentioned_parts.append(english_part)
    if mentioned_parts:
        context.append(f"Affected area: {', '.join(mentioned_parts[:4])}.")

    return context


def trim_detail_note(note: str, limit: int = 260) -> str:
    note = clean_text(note)
    if len(note) <= limit:
        return note
    return note[: limit - 1].rstrip(" ,.;、。") + "…"


def build_description_append(
    *,
    title: str,
    book_count: Optional[int],
    evidence: str,
    weight_kg: Optional[float],
    ficp_charge: Optional[FICPCharge],
    shipping_usd: Optional[float],
    source_url: str,
    buyer_detail_notes: Optional[list[str]] = None,
) -> str:
    buyer_detail_notes = buyer_detail_notes or []
    if not book_count and not buyer_detail_notes:
        return ""

    lines = [
        AUTOFILL_MARKER_START,
        '<div style="margin-top:16px; padding-top:12px; border-top:1px solid #d0d5dd;">',
        "<p><strong>Item details</strong></p>",
        "<ul>",
    ]
    if book_count:
        lines.append(f"<li>This manga set includes {book_count} books.</li>")
    for note in buyer_detail_notes:
        lines.append(f"<li>{html_escape(note)}</li>")
    lines.extend(
        [
            "</ul>",
            '<p style="font-size:12px; color:#667085;">Please review photos for exact condition.</p>',
            "</div>",
            AUTOFILL_MARKER_END,
        ]
    )
    return "\n".join(lines)


def build_description_detail_summary(
    *,
    book_count: Optional[int],
    evidence: str,
    buyer_detail_notes: list[str],
    addition: str,
) -> str:
    summary: list[str] = []
    if book_count:
        summary.append(f"Description includes total book count: {book_count} books.")
    if buyer_detail_notes:
        summary.extend(buyer_detail_notes)
    elif addition:
        summary.append("No buyer-relevant condition details were added.")
    else:
        summary.append("No Description details were added.")
    return "; ".join(summary)


def build_description_append_display_text(addition: str) -> str:
    """Descriptionに実際へ追記したHTMLブロックを、画面確認用の英文テキストへ整える。"""
    source = str(addition or "").strip()
    if not source:
        return ""
    source = source.replace(AUTOFILL_MARKER_START, "").replace(AUTOFILL_MARKER_END, "")
    source = re.sub(r"<p>\s*<strong>(.*?)</strong>\s*</p>", r"\1\n", source, flags=re.I | re.S)
    source = re.sub(r"<li>(.*?)</li>", r"- \1\n", source, flags=re.I | re.S)
    source = re.sub(r"<p[^>]*>(.*?)</p>", r"\1\n", source, flags=re.I | re.S)
    source = re.sub(r"<br\s*/?>", "\n", source, flags=re.I)
    source = re.sub(r"</(?:ul|div)>", "\n", source, flags=re.I)
    source = re.sub(r"<[^>]+>", " ", source)
    source = unescape(source)
    lines = [re.sub(r"\s+", " ", line).strip() for line in source.splitlines()]
    return "\n".join(line for line in lines if line)


def format_volume_scope_japanese(scope: str) -> str:
    numbers = re.findall(r"\d{1,3}", str(scope or ""))
    if not numbers:
        return clean_text(scope)
    if len(numbers) >= 2 and re.search(r"-|〜|～|~", str(scope)):
        return f"{numbers[0]}〜{numbers[-1]}巻"
    if len(numbers) == 1:
        return f"{numbers[0]}巻"
    if len(numbers) == 2:
        return f"{numbers[0]}巻と{numbers[1]}巻"
    return "、".join(f"{number}巻" for number in numbers[:-1]) + f"、{numbers[-1]}巻"


def has_untranslated_english(text: object) -> bool:
    return bool(re.search(r"[A-Za-z]{3,}", str(text or "")))


def split_english_description_sentences(text: str) -> list[str]:
    """Description表示文を、翻訳しやすい短い英文単位へ分ける。"""
    source = clean_text(text).strip(" -・")
    if not source:
        return []
    source = re.sub(r"\s+-\s+", ". ", source)
    parts = re.split(r"(?<=[.!?])\s+", source)
    sentences: list[str] = []
    buffer = ""
    for part in parts:
        part = part.strip()
        part = re.sub(r"([.!?]){2,}$", r"\1", part)
        if not part:
            continue
        # Quoted title abbreviations are rare here, but keep very short fragments with the next part.
        if buffer:
            part = f"{buffer} {part}"
            buffer = ""
        if len(part) <= 3 and not part.endswith((".", "!", "?")):
            buffer = part
            continue
        sentences.append(part)
    if buffer:
        sentences.append(buffer)
    return sentences


def translate_english_description_sentence_to_japanese(sentence: str) -> str:
    """CSVへ追記した英語Descriptionの1文を、日本語確認用に翻訳する。"""
    source = clean_text(sentence).strip(" -・")
    source = re.sub(r"([.!?]){2,}$", r"\1", source)
    if not source:
        return ""
    if not has_untranslated_english(source):
        return source

    translated = source
    translated = re.sub(
        r"\b(?:The\s+)?Set includes volumes? (\d{1,3}) through (\d{1,3})\.",
        lambda match: f"{match.group(1)}〜{match.group(2)}巻を含みます。",
        translated,
        flags=re.I,
    )
    translated = re.sub(
        r"\b(?:The\s+)?Set includes volumes? ([\d,\sand-]+)\.",
        lambda match: f"{format_volume_scope_japanese(match.group(1))}を含みます。",
        translated,
        flags=re.I,
    )

    fallback_patterns = [
        (r"This manga set includes (\d{1,3}) books?\.", r"この漫画セットは\1冊です。"),
        (r"\bItem details\b\.?", "商品詳細"),
        (r"Complete (\d{1,3})[- ]volume set(?: of .+)?\.", r"全\1巻セットです。"),
        (r"Complete (\d{1,3})[- ]book set(?: of .+)?\.", r"全\1冊セットです。"),
        (r"Complete set of (\d{1,3}) volumes?\.", r"全\1巻セットです。"),
        (r"Complete set of (\d{1,3}) books?\.", r"全\1冊セットです。"),
        (r"Complete set\.\s*of (\d{1,3}) volumes?\.", r"全\1巻セットです。"),
        (r"Complete set\.", "完結セットです。"),
        (r"Volumes? are unread and have been stored since purchase\.", "各巻は未読で、購入後に保管されていたと説明されています。"),
        (r"Volumes? are unread\.", "各巻は未読です。"),
        (r"Volumes? show minimal signs of use\.", "各巻の使用感は少なめです。"),
        (r"Volumes? show minimal signs of wear\.", "各巻の使用感は少なめです。"),
        (r"Brand new and unread\.", "新品・未読です。"),
        (r"New and unread\.", "新品・未読です。"),
        (r"Brand new and never used\.", "新品・未使用です。"),
        (r"Purchased new and never used\.", "新品で購入後、未使用です。"),
        (r"Unread condition\.", "未読の状態です。"),
        (r"Never used\.", "未使用です。"),
        (r"Unread and stored since purchase\.", "未読で、購入後に保管されていたと説明されています。"),
        (r"Stored since purchase\.", "購入後に保管されていたと説明されています。"),
        (r"Minor imperfections may be present due to personal storage\.", "個人保管品のため、軽微な傷みがある可能性があります。"),
        (r"Minor imperfections due to storage may be present\.", "保管に伴う軽微な傷みがある可能性があります。"),
        (r"Minor storage wear may be present\.", "保管に伴う軽微な傷みがある可能性があります。"),
        (r"Storage wear may be present\.", "保管に伴う傷みがある可能性があります。"),
        (r"May show minor storage wear\.", "保管に伴う軽微な傷みが見られる可能性があります。"),
        (r"Minor imperfections may be present\.", "軽微な傷みがある可能性があります。"),
        (r"Personal storage condition\.", "個人保管品です。"),
        (r"Stored in personal collection\.", "個人コレクションとして保管されていたと説明されています。"),
        (r"Appears to be in near-unused condition\.", "未使用に近い状態です。"),
        (r"Appears to be near-unused\.", "未使用に近い状態です。"),
        (r"Appears to be close to unused\.", "未使用に近い状態です。"),
        (r"Appears to be in near-new condition\.", "新品に近い状態です。"),
        (r"Appears to be near-new\.", "新品に近い状態です。"),
        (r"Shows minimal signs of use\.", "使用感は少なめです。"),
        (r"Shows minimal signs of wear\.", "使用感は少なめです。"),
        (r"Condition is ['\"]?Near Mint['\"]? with little feeling of use\.", "使用感が少ない、未使用に近い状態です。"),
        (r"Condition is ['\"]?Near Mint['\"]?\.", "未使用に近い状態です。"),
        (r"Condition is ['\"]?Mint['\"]?\.", "新品に近い状態です。"),
        (r"Condition is ['\"]?Good['\"]?\.", "良好な状態です。"),
        (r"Minimal signs of use\.", "使用感は少なめです。"),
        (r"Minimal signs of wear\.", "使用感は少なめです。"),
        (r"Near mint condition\.", "未使用に近い状態です。"),
        (r"Mint condition\.", "新品に近い状態です。"),
        (r"Good condition\.", "良好な状態です。"),
        (r"Please review photos for exact condition\.", "正確な状態は写真で確認してください。"),
        (r"Please check photos\.", "写真で状態を確認してください。"),
    ]
    for pattern, replacement in fallback_patterns:
        translated = re.sub(pattern, replacement, translated, flags=re.I)

    if not has_untranslated_english(translated):
        return translated

    # 未知の英文でも「上の英語欄で確認」という逃げ方はしない。
    # 商品説明として頻出する語から、最低限の意味が分かる日本語へ寄せる。
    lower = source.lower()
    if "complete" in lower and re.search(r"\d{1,3}\s*[- ]?(?:volume|book)", lower):
        number = re.search(r"(\d{1,3})\s*[- ]?(?:volume|book)", lower)
        if number:
            unit = "巻" if "volume" in lower else "冊"
            return f"全{number.group(1)}{unit}セットです。"
    if "near mint" in lower or "near-unused" in lower or "close to unused" in lower:
        if "little" in lower or "minimal" in lower:
            return "使用感が少ない、未使用に近い状態です。"
        return "未使用に近い状態です。"
    if "minimal signs" in lower or "little feeling of use" in lower:
        return "使用感は少なめです。"
    if "unread" in lower and ("new" in lower or "brand new" in lower):
        return "新品・未読です。"
    if "unread" in lower:
        return "未読の状態です。"
    if "never used" in lower or "unused" in lower:
        return "未使用です。"
    if "storage" in lower and ("imperfection" in lower or "wear" in lower):
        return "保管に伴う軽微な傷みがある可能性があります。"
    if "condition" in lower:
        return "状態に関する説明があります。"
    return "追加の商品状態説明があります。"


def translate_unhandled_description_english(line: str) -> str:
    """AIの自由文で残った英文を、文単位で日本語へ翻訳する。"""
    sentences = split_english_description_sentences(line)
    if not sentences:
        return ""
    translated = [translate_english_description_sentence_to_japanese(sentence) for sentence in sentences]
    return " ".join(part for part in translated if part)


def translate_description_added_text_to_japanese(text: object) -> str:
    """画面確認用に、CSVへ追記される英文Descriptionの要点を日本語へ置き換える。"""
    source = unescape(str(text or "")).strip()
    if not source:
        return ""
    if contains_japanese_text(source) and not re.search(r"[A-Za-z]{3,}", source):
        return source

    phrase_replacements = [
        (r"\bItem details\b", "商品詳細"),
        (r"This manga set includes (\d+) books\.", r"この漫画セットは\1冊です。"),
        (r"All volumes are first editions\.", "全巻初版です。"),
        (r"First edition volume\(s\) may be included\.", "初版の巻が含まれている可能性があります。"),
        (r"Little to no page tanning or sun fading is mentioned\.", "日焼けや色あせはほとんどないと説明されています。"),
        (r"Page tanning or sun fading may be present\.", "日焼けや色あせがある可能性があります。"),
        (r"Shrink wrap is mentioned as included\. Please review photos to confirm which volume\(s\) are shrink-wrapped\.", "シュリンク付きの記載があります。どの巻が対象か写真で確認してください。"),
        (r"Shrink wrap condition should be checked in the photos\.", "シュリンクの状態は写真で確認してください。"),
        (r"Shrink wrap is included\.", "シュリンク付きです。"),
        (r"Shrink wrap is not included\.", "シュリンクは付属しません。"),
        (r"All volumes are shrink-wrapped\.", "全巻シュリンク付きです。"),
        (r"Please review photos for exact condition\.", "正確な状態は写真で確認してください。"),
        (r"Condition: clean/good condition\.", "状態: きれい・良好な状態です。"),
        (r"Condition: close to unused\.", "状態: 未使用に近いです。"),
        (r"Condition: new/unread\.", "状態: 新品・未読です。"),
        (r"Condition: new/unused\.", "状態: 新品・未使用です。"),
        (r"Condition: no noticeable scratches or stains\.", "状態: 目立った傷や汚れはありません。"),
        (r"Condition: some scratches or stains\.", "状態: やや傷や汚れがあります。"),
        (r"Condition: scratches or stains\.", "状態: 傷や汚れがあります。"),
        (r"Condition: poor overall condition\.", "状態: 全体的に状態が悪い可能性があります。"),
        (r"Former rental copy/copies may be included\.", "レンタル落ちの巻が含まれる可能性があります。"),
        (r"Former comic cafe/library-use copies may be included\.", "漫画喫茶・図書館利用品の巻が含まれる可能性があります。"),
        (r"Writing or markings may be present\.", "書き込みやマーキングがある可能性があります。"),
        (r"Cut/scanned-copy condition may be present\.", "裁断済み・スキャン用の状態である可能性があります。"),
        (r"Water exposure or water damage may be present\.", "水濡れ・水濡れ跡がある可能性があります。"),
        (r"Tears may be present\.", "破れがある可能性があります。"),
        (r"Creases or folds may be present\.", "折れやシワがある可能性があります。"),
        (r"Stains or dirt may be present\.", "シミや汚れがある可能性があります。"),
        (r"Scratches or scuffs may be present\.", "傷やスレがある可能性があります。"),
        (r"Obi band is included\.", "帯が付属します。"),
        (r"Obi band is not included\.", "帯は付属しません。"),
        (r"Bonus items or extras are included\.", "特典・付属品が含まれます。"),
        (r"Some items or details may be missing\.", "一部の付属品や詳細が欠けている可能性があります。"),
        (r"Application/coupon ticket has been cut out or removed\.", "応募券・クーポン券は切り取り済み、または取り除かれています。"),
        (r"No folds or writing noted\.", "折れや書き込みはないと説明されています。"),
        (r"No folds or writing are noted\.", "折れや書き込みはないと説明されています。"),
        (r"No writing or markings noted\.", "書き込みやマーキングはないと説明されています。"),
        (r"Volumes? show minimal signs of use\.", "各巻の使用感は少なめです。"),
        (r"Volumes? show minimal signs of wear\.", "各巻の使用感は少なめです。"),
        (r"Complete (\d{1,3})[- ]volume set(?: of .+)?\.", r"全\1巻セットです。"),
        (r"Complete (\d{1,3})[- ]book set(?: of .+)?\.", r"全\1冊セットです。"),
        (r"Complete set of (\d{1,3}) volumes?\.", r"全\1巻セットです。"),
        (r"Complete set of (\d{1,3}) books?\.", r"全\1冊セットです。"),
        (r"Volumes? are unread and have been stored since purchase\.", "各巻は未読で、購入後に保管されていたと説明されています。"),
        (r"Volumes? are unread\.", "各巻は未読です。"),
        (r"Brand new and unread\.", "新品・未読です。"),
        (r"New and unread\.", "新品・未読です。"),
        (r"Brand new and never used\.", "新品・未使用です。"),
        (r"Purchased new and never used\.", "新品で購入後、未使用です。"),
        (r"Unread condition\.", "未読の状態です。"),
        (r"Never used\.", "未使用です。"),
        (r"Unread and stored since purchase\.", "未読で、購入後に保管されていたと説明されています。"),
        (r"Stored since purchase\.", "購入後に保管されていたと説明されています。"),
        (r"Minor imperfections may be present due to personal storage\.", "個人保管品のため、軽微な傷みがある可能性があります。"),
        (r"Minor imperfections due to storage may be present\.", "保管に伴う軽微な傷みがある可能性があります。"),
        (r"Minor storage wear may be present\.", "保管に伴う軽微な傷みがある可能性があります。"),
        (r"Storage wear may be present\.", "保管に伴う傷みがある可能性があります。"),
        (r"May show minor storage wear\.", "保管に伴う軽微な傷みが見られる可能性があります。"),
        (r"Minor imperfections may be present\.", "軽微な傷みがある可能性があります。"),
        (r"Appears to be in near-unused condition\.", "未使用に近い状態です。"),
        (r"Appears to be near-unused\.", "未使用に近い状態です。"),
        (r"Appears to be close to unused\.", "未使用に近い状態です。"),
        (r"Appears to be in near-new condition\.", "新品に近い状態です。"),
        (r"Appears to be near-new\.", "新品に近い状態です。"),
        (r"Condition is ['\"]?Near Mint['\"]? with little feeling of use\.", "使用感が少ない、未使用に近い状態です。"),
        (r"Condition is ['\"]?Near Mint['\"]?\.", "未使用に近い状態です。"),
        (r"Condition is ['\"]?Mint['\"]?\.", "新品に近い状態です。"),
        (r"Condition is ['\"]?Good['\"]?\.", "良好な状態です。"),
        (r"Shows minimal signs of use\.", "使用感は少なめです。"),
        (r"Shows minimal signs of wear\.", "使用感は少なめです。"),
        (r"Minimal signs of use\.", "使用感は少なめです。"),
        (r"Minimal signs of wear\.", "使用感は少なめです。"),
    ]

    translated_lines: list[str] = []
    source = re.sub(r"\s+-\s+", "\n- ", source)
    for raw_line in source.splitlines():
        line = clean_text(raw_line)
        if not line:
            continue
        bullet = line.startswith("- ")
        if bullet:
            line = line[2:].strip()

        line = re.sub(
            r"\bVolumes ([\d,\sand-]+) are shrink-wrapped\.",
            lambda match: f"{format_volume_scope_japanese(match.group(1))}はシュリンク付きです。",
            line,
            flags=re.I,
        )
        line = re.sub(
            r"\bVolume (\d{1,3}) is shrink-wrapped\.",
            lambda match: f"{match.group(1)}巻はシュリンク付きです。",
            line,
            flags=re.I,
        )
        line = re.sub(
            r"\bVolumes ([\d,\sand-]+) are not shrink-wrapped\.",
            lambda match: f"{format_volume_scope_japanese(match.group(1))}はシュリンク付きではありません。",
            line,
            flags=re.I,
        )
        line = re.sub(
            r"\bVolume (\d{1,3}) is not shrink-wrapped\.",
            lambda match: f"{match.group(1)}巻はシュリンク付きではありません。",
            line,
            flags=re.I,
        )
        line = re.sub(
            r"\bVolumes ([\d,\sand-]+) are first editions\.",
            lambda match: f"{format_volume_scope_japanese(match.group(1))}は初版です。",
            line,
            flags=re.I,
        )
        line = re.sub(
            r"\bVolume (\d{1,3}) is a first edition\.",
            lambda match: f"{match.group(1)}巻は初版です。",
            line,
            flags=re.I,
        )
        line = re.sub(
            r"\bVolume ([\d,\sand-]+) may have the noted condition\.",
            lambda match: f"{format_volume_scope_japanese(match.group(1))}に記載された状態がある可能性があります。",
            line,
            flags=re.I,
        )
        line = re.sub(
            r"\b(?:The\s+)?Set includes volumes? (\d{1,3}) through (\d{1,3})\.",
            lambda match: f"{match.group(1)}〜{match.group(2)}巻を含みます。",
            line,
            flags=re.I,
        )
        line = re.sub(
            r"\b(?:The\s+)?Set includes volumes? ([\d,\sand-]+)\.",
            lambda match: f"{format_volume_scope_japanese(match.group(1))}を含みます。",
            line,
            flags=re.I,
        )
        line = re.sub(
            r"\bIncludes volumes? (\d{1,3}) through (\d{1,3})\.",
            lambda match: f"{match.group(1)}〜{match.group(2)}巻を含みます。",
            line,
            flags=re.I,
        )
        line = re.sub(
            r"\bIncludes volumes? ([\d,\sand-]+)\.",
            lambda match: f"{format_volume_scope_japanese(match.group(1))}を含みます。",
            line,
            flags=re.I,
        )
        line = re.sub(
            r"\bVolumes? ([\d,\sand-]+) (?:has|have) been read once\.",
            lambda match: f"{format_volume_scope_japanese(match.group(1))}は一度読まれています。",
            line,
            flags=re.I,
        )
        line = re.sub(
            r"\bVolumes? ([\d,\sand-]+) (?:is|are) unopened\.",
            lambda match: f"{format_volume_scope_japanese(match.group(1))}は未開封です。",
            line,
            flags=re.I,
        )
        line = re.sub(
            r"\bOriginal obi/bands? (?:is|are) missing for volumes? ([\d,\sand-]+)\.",
            lambda match: f"{format_volume_scope_japanese(match.group(1))}は元の帯が欠品しています。",
            line,
            flags=re.I,
        )
        line = re.sub(
            r"\bObi/bands? (?:is|are) missing for volumes? ([\d,\sand-]+)\.",
            lambda match: f"{format_volume_scope_japanese(match.group(1))}は帯が欠品しています。",
            line,
            flags=re.I,
        )
        line = re.sub(
            r"Affected area: ([^.]+)\.",
            lambda match: f"該当箇所: {translate_condition_parts_to_japanese(match.group(1))}。",
            line,
            flags=re.I,
        )
        for pattern, replacement in phrase_replacements:
            line = re.sub(pattern, replacement, line, flags=re.I)
        line = translate_unhandled_description_english(line)
        translated_lines.append(("・" if bullet else "") + line)

    return "\n".join(translated_lines)


def translate_condition_parts_to_japanese(parts: str) -> str:
    translated = str(parts or "")
    replacements = {
        "front cover": "表紙",
        "back cover": "裏表紙",
        "page edges": "小口",
        "pages": "ページ",
        "cover": "カバー",
        "obi band": "帯",
        "bonus item/extras": "特典・付属品",
    }
    for english, japanese in replacements.items():
        translated = re.sub(re.escape(english), japanese, translated, flags=re.I)
    translated = translated.replace(", and ", "、").replace(" and ", "と").replace(", ", "、")
    return translated


def html_escape(value: object) -> str:
    text = str(value or "")
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def append_description(existing_description: str, addition: str) -> str:
    pattern = re.compile(
        rf"\s*{re.escape(AUTOFILL_MARKER_START)}.*?{re.escape(AUTOFILL_MARKER_END)}",
        flags=re.S,
    )
    cleaned = pattern.sub("", str(existing_description or "")).rstrip()
    addition = str(addition or "").strip()
    if not addition:
        return cleaned.strip()
    if not cleaned:
        return addition
    return insert_html_block(cleaned, addition).strip()


def insert_html_block(existing_html: str, addition: str) -> str:
    cdata_full_match = re.match(r"^(\s*<!\[CDATA\[)(.*?)(\]\]>\s*)$", existing_html, flags=re.S)
    if cdata_full_match:
        prefix, inner, suffix = cdata_full_match.groups()
        return f"{prefix}{insert_html_block(inner.strip(), addition)}{suffix}"

    product_overview_html = insert_into_product_overview(existing_html, addition)
    if product_overview_html:
        return product_overview_html

    for tag in ("</body>", "</main>", "</section>", "</article>", "</div>"):
        matches = list(re.finditer(re.escape(tag), existing_html, flags=re.I))
        if matches:
            match = matches[-1]
            return f"{existing_html[:match.start()].rstrip()}\n\n{addition}\n{existing_html[match.start():]}"

    return f"{existing_html}\n\n{addition}"


def insert_into_product_overview(existing_html: str, addition: str) -> str:
    if BeautifulSoup is None:
        return ""
    if not re.search(r"Product\s+Overview", existing_html, flags=re.I):
        return ""

    soup = BeautifulSoup(existing_html, "html.parser")
    heading_text = soup.find(string=lambda text: bool(text and re.search(r"\bProduct\s+Overview\b", str(text), flags=re.I)))
    if not heading_text:
        return ""

    heading_element = heading_text.parent
    if heading_element is None:
        return ""

    target = find_product_overview_content_container(heading_element)
    fragment = BeautifulSoup(addition, "html.parser")
    if target is not None:
        target.append(fragment)
        return str(soup)

    heading_element.insert_after(fragment)
    return str(soup)


def find_product_overview_content_container(heading_element) -> object:
    section_heading_pattern = re.compile(
        r"\b(Payment\s+Details|Shipping\s+Information|Return|Returns|Customs\s*&\s*Duties|Customs|Duties)\b",
        flags=re.I,
    )
    for sibling in heading_element.find_next_siblings():
        text = sibling.get_text(" ", strip=True) if hasattr(sibling, "get_text") else clean_text(sibling)
        if section_heading_pattern.search(text):
            return None
        if getattr(sibling, "name", None) and text:
            return sibling
    return None


def process_dataframe(
    frame: pd.DataFrame,
    config: ProcessingConfig,
    row_indices: Optional[Iterable[int]] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> pd.DataFrame:
    output = frame.copy().fillna("")
    target_indices = list(row_indices) if row_indices is not None else list(output.index)

    for col in [
        "Inferred Source URL",
        "Source URL Confidence",
        "Source URL Evidence",
        "Source Listing Title",
        "Source Listing Price",
        "Source Listing Description",
        "Source Listing Detail Preview",
        "Source Image URLs",
        "Detected Book Count",
        "Book Count Evidence",
        "Book Count Status",
        "Book Count Exclusion Limit",
        "Reference Book Count",
        "Reference Count Source",
        "Reference Count Confidence",
        "Reference Count Evidence",
        "Reference Count Status",
        "Estimated Book Weight g",
        "Book Weight Evidence",
        "Estimated Packaging Weight kg",
        "Packaging Materials",
        "Packaging Weight Evidence",
        "Estimated Weight kg",
        "Estimated Actual Weight kg",
        "Dimensional Weight kg",
        "Billable Weight kg",
        "Billable Weight Source",
        "Package Length cm",
        "Package Width cm",
        "Package Height cm",
        "Package Dimension Source",
        "Dimensional Divisor",
        "FICP Zone",
        "FICP US Zone",
        "FICP Billed Weight kg",
        "FICP Base Shipping JPY",
        "FICP Base Shipping USD",
        "FICP Fuel Surcharge Percent",
        "FICP Fuel Surcharge JPY",
        "FICP Fuel Surcharge USD",
        "FICP Shipping JPY",
        "FICP Shipping USD",
        "FICP Shipping Includes Fuel Surcharge",
        "Listing Eligibility",
        "Exclusion Reason",
        "Exclusion Evidence",
        "Processing Result",
        "Processing Severity",
        "Processing Diagnostics",
        "Needs Review",
        "Needs Review Reason",
        "Scrape Status",
        "Main Image URL",
        "Specifics Fill Notes",
        "Specifics Filled Fields",
        "Specifics Existing Fields",
        "Specifics Not Filled Fields",
        "Description Added Text",
        "Description Added Japanese",
        "Description Added HTML",
        "Description Detail Notes",
        "AI Provider",
        "AI Model",
        "AI Enrichment Status",
        "AI Description Notes",
        "AI Specifics Suggestions",
    ]:
        if col not in output.columns:
            output[col] = ""

    for spec_col in DEFAULT_SPECIFIC_COLUMNS:
        if spec_col not in output.columns:
            output[spec_col] = ""

    specific_columns = get_specific_columns(output.columns, include_defaults=True)

    total = len(target_indices)
    browser_scraper: Optional[BrowserListingScraper] = BrowserListingScraper() if config.enable_scrape and config.enable_browser_scrape else None
    try:
        for position, index in enumerate(target_indices, start=1):
            row = output.loc[index].copy()
            provided_url = get_row_value(row, config.url_col)
            csv_image_urls = parse_image_urls(get_row_value(row, config.image_col))
            row["Source Image URLs"] = "|".join(csv_image_urls)
            source_url, inferred_source, source_confidence, source_evidence = resolve_source_url(provided_url, csv_image_urls)
            if (
                source_url
                and config.url_col
                and config.url_col in row.index
                and (is_blank(row.get(config.url_col, "")) or is_likely_image_url(row.get(config.url_col, "")))
            ):
                row[config.url_col] = source_url

            listing = (
                scrape_listing(source_url, use_browser=config.enable_browser_scrape, browser_scraper=browser_scraper)
                if config.enable_scrape
                else ListingData(source_url=source_url, status="scrape disabled")
            )
            csv_title = get_row_value(row, config.title_col)
            csv_description = get_row_value(row, config.description_col)
            csv_image = first_nonblank(*csv_image_urls)
            csv_price = get_row_value(row, config.price_col)

            title = first_nonblank(listing.title, csv_title)
            description = first_nonblank(listing.description, csv_description)
            image_url = first_nonblank(listing.image_url, csv_image)
            price = first_nonblank(listing.price, csv_price)
            combined_text = "\n".join(
                str(part)
                for part in [
                    title,
                    description,
                    listing.details_text,
                    "\n".join(str(value) for value in row.values),
                ]
                if part
            )
            exclusion = detect_unlistable_listing_issue(title, listing.description, listing.details_text, csv_description)
            if not exclusion.excluded:
                exclusion = detect_magazine_listing_issue(title, listing.description, listing.details_text, csv_description)
            if exclusion.excluded:
                row["Inferred Source URL"] = inferred_source.url
                row["Source URL Confidence"] = source_confidence
                row["Source URL Evidence"] = source_evidence
                row["Source Listing Title"] = truncate_text(listing.title, 300)
                row["Source Listing Price"] = truncate_text(listing.price, 80)
                row["Source Listing Description"] = truncate_text(clean_source_listing_description(listing.description), 700)
                row["Source Listing Detail Preview"] = build_source_detail_preview(listing.description, listing.details_text)
                row["Listing Eligibility"] = "Excluded"
                row["Exclusion Reason"] = exclusion.reason
                row["Exclusion Evidence"] = exclusion.evidence
                row["Scrape Status"] = f"excluded: {listing.status}"
                row["Main Image URL"] = image_url
                row["AI Enrichment Status"] = "skipped: excluded"
                row["Description Added Text"] = f"出品除外: {exclusion.reason}。ダウンロードCSVから除外します。"
                row["Description Added Japanese"] = row["Description Added Text"]
                row["Description Detail Notes"] = f"Excluded from export CSV: {exclusion.reason}; evidence: {exclusion.evidence}"
                row = apply_processing_diagnostics(row)
                output.loc[index, row.index] = row
                if progress_callback:
                    progress_callback(position, total, f"出品除外: {title or f'row {index + 1}'}")
                if config.enable_scrape and config.request_delay_seconds > 0 and position < total:
                    time.sleep(config.request_delay_seconds)
                continue

            condition_evidence_text = build_condition_evidence_text(
                title=title,
                listing_description=listing.description,
                listing_details_text=listing.details_text,
                csv_description=csv_description,
            )

            book_count, evidence = detect_book_count(combined_text)
            ai_enrichment = AIEnrichment(status="disabled")
            reference_count_result = ReferenceBookCountResult(status="not needed")
            if not book_count:
                reference_count_result = lookup_complete_set_book_count(
                    title=title,
                    details_text=listing.details_text,
                    combined_text=combined_text,
                    enable_reference_lookup=config.enable_reference_lookup,
                )
                if reference_count_result.book_count and reference_count_result.confidence in {"high", "medium"}:
                    book_count = reference_count_result.book_count
                    evidence = reference_count_result.evidence
            book_count_status = "ok" if book_count else "冊数判定不能: タイトル・説明から巻数を特定できません"
            if not book_count:
                missing_reason, missing_evidence = exclusion_reason_for_missing_book_count(reference_count_result)
                book_count_status = f"冊数判定不能: {missing_reason}: {missing_evidence or reference_count_result.status}"
            book_weight_estimate = estimate_book_weight_g(combined_text, config.book_weight_g)
            package_length_cm, package_width_cm, package_height_cm, package_dimension_source = resolve_package_dimensions_cm(
                book_count,
                config.package_length_cm,
                config.package_width_cm,
                config.package_height_cm,
            )
            packaging_estimate = estimate_packaging_weight_kg(
                book_count,
                package_length_cm,
                package_width_cm,
                package_height_cm,
                config.packaging_weight_kg,
            )
            weight_kg = calculate_weight_kg(book_count, book_weight_estimate.weight_g, packaging_estimate.weight_kg)
            dimensional_weight_kg = calculate_dimensional_weight_kg(
                package_length_cm,
                package_width_cm,
                package_height_cm,
                config.dimensional_divisor_cm,
            )
            billable_weight_kg, billable_weight_source = calculate_billable_weight_kg(weight_kg, dimensional_weight_kg)
            ficp_charge: Optional[FICPCharge] = None
            base_shipping_usd: Optional[float] = None
            fuel_surcharge_jpy: Optional[int] = None
            fuel_surcharge_usd: Optional[float] = None
            total_shipping_jpy: Optional[int] = None
            shipping_usd: Optional[float] = None
            if billable_weight_kg:
                ficp_charge = calculate_ficp_shipping(billable_weight_kg, config.zone)
                total_shipping_jpy, fuel_surcharge_jpy = calculate_shipping_total_with_fuel(
                    ficp_charge.shipping_jpy,
                    config.fuel_surcharge_percent,
                )
                base_shipping_usd = jpy_to_usd(ficp_charge.shipping_jpy, config.exchange_rate_jpy_per_usd)
                fuel_surcharge_usd = jpy_to_usd(fuel_surcharge_jpy, config.exchange_rate_jpy_per_usd)
                shipping_usd = jpy_to_usd(total_shipping_jpy, config.exchange_rate_jpy_per_usd)

            shipping_exclusion_reason = ""
            shipping_exclusion_evidence = ""
            if not shipping_usd:
                if not book_count:
                    shipping_exclusion_reason, shipping_exclusion_evidence = exclusion_reason_for_missing_book_count(reference_count_result)
                if not shipping_exclusion_reason:
                    shipping_exclusion_reason = "Shipping could not be calculated"
                    shipping_exclusion_evidence = book_count_status or "Book count, weight, or FICP shipping was not calculated."
            if shipping_exclusion_reason:
                row["Inferred Source URL"] = inferred_source.url
                row["Source URL Confidence"] = source_confidence
                row["Source URL Evidence"] = source_evidence
                row["Source Listing Title"] = truncate_text(listing.title, 300)
                row["Source Listing Price"] = truncate_text(listing.price, 80)
                row["Source Listing Description"] = truncate_text(clean_source_listing_description(listing.description), 700)
                row["Source Listing Detail Preview"] = build_source_detail_preview(listing.description, listing.details_text)
                row["Detected Book Count"] = str(book_count or "")
                row["Book Count Evidence"] = evidence
                row["Book Count Status"] = book_count_status
                row["Book Count Exclusion Limit"] = str(config.max_book_count_for_export or "")
                row = apply_reference_count_result_to_row(row, reference_count_result)
                row["Estimated Book Weight g"] = str(book_weight_estimate.weight_g if book_count else "")
                row["Book Weight Evidence"] = book_weight_estimate.evidence if book_count else ""
                row["Estimated Packaging Weight kg"] = f"{packaging_estimate.weight_kg:.3f}" if book_count else ""
                row["Packaging Materials"] = packaging_estimate.materials if book_count else ""
                row["Packaging Weight Evidence"] = packaging_estimate.evidence if book_count else ""
                row["Estimated Weight kg"] = f"{weight_kg:.3f}" if weight_kg else ""
                row["Estimated Actual Weight kg"] = f"{weight_kg:.3f}" if weight_kg else ""
                row["Dimensional Weight kg"] = f"{dimensional_weight_kg:.3f}" if dimensional_weight_kg else ""
                row["Billable Weight kg"] = f"{billable_weight_kg:.3f}" if billable_weight_kg else ""
                row["Billable Weight Source"] = billable_weight_source
                row["Package Length cm"] = f"{package_length_cm:.1f}" if package_length_cm else ""
                row["Package Width cm"] = f"{package_width_cm:.1f}" if package_width_cm else ""
                row["Package Height cm"] = f"{package_height_cm:.1f}" if package_height_cm else ""
                row["Package Dimension Source"] = package_dimension_source
                row["Dimensional Divisor"] = str(config.dimensional_divisor_cm)
                row["FICP Zone"] = config.zone
                row["FICP US Zone"] = ficp_us_zone_label(config.zone)
                row["FICP Billed Weight kg"] = f"{ficp_charge.billed_weight_kg:.3f}" if ficp_charge else ""
                row["FICP Base Shipping JPY"] = str(ficp_charge.shipping_jpy) if ficp_charge else ""
                row["FICP Base Shipping USD"] = f"{base_shipping_usd:.2f}" if base_shipping_usd is not None else ""
                row["FICP Fuel Surcharge Percent"] = f"{config.fuel_surcharge_percent:.2f}" if ficp_charge else ""
                row["FICP Fuel Surcharge JPY"] = str(fuel_surcharge_jpy) if fuel_surcharge_jpy is not None else ""
                row["FICP Fuel Surcharge USD"] = f"{fuel_surcharge_usd:.2f}" if fuel_surcharge_usd is not None else ""
                row["FICP Shipping JPY"] = str(total_shipping_jpy) if total_shipping_jpy is not None else ""
                row["FICP Shipping USD"] = f"{shipping_usd:.2f}" if shipping_usd is not None else ""
                row["FICP Shipping Includes Fuel Surcharge"] = "Yes" if ficp_charge and config.fuel_surcharge_percent > 0 else "No" if ficp_charge else ""
                row["Listing Eligibility"] = "Excluded"
                row["Exclusion Reason"] = shipping_exclusion_reason
                row["Exclusion Evidence"] = shipping_exclusion_evidence
                row["USDJPY Exchange Rate"] = f"{config.exchange_rate_jpy_per_usd:.4f}"
                row["USDJPY Exchange Rate Source"] = config.exchange_rate_source
                row["USDJPY Exchange Rate Date"] = config.exchange_rate_date
                row["Scrape Status"] = f"excluded: {listing.status}"
                row["Main Image URL"] = image_url
                row["AI Provider"] = ai_enrichment.provider or config.ai_provider
                row["AI Model"] = ai_enrichment.model or config.ai_model
                row["AI Enrichment Status"] = ai_enrichment.status
                row["Description Added Text"] = (
                    "Excluded from export CSV: shipping could not be calculated with sufficient confidence."
                )
                row["Description Added Japanese"] = (
                    "出品除外: 送料計算に必要な冊数または重量を十分な確度で判定できないため、ダウンロードCSVから除外します。"
                )
                row["Description Detail Notes"] = (
                    f"Excluded from export CSV: {shipping_exclusion_reason}; "
                    f"evidence: {shipping_exclusion_evidence}"
                )
                row = apply_processing_diagnostics(row)
                output.loc[index, row.index] = row
                if progress_callback:
                    progress_callback(position, total, f"excluded: {title or f'row {index + 1}'}")
                if config.enable_scrape and config.request_delay_seconds > 0 and position < total:
                    time.sleep(config.request_delay_seconds)
                continue

            count_limit_exclusion = detect_book_count_limit_issue(book_count, config.max_book_count_for_export)
            if count_limit_exclusion.excluded:
                row["Inferred Source URL"] = inferred_source.url
                row["Source URL Confidence"] = source_confidence
                row["Source URL Evidence"] = source_evidence
                row["Source Listing Title"] = truncate_text(listing.title, 300)
                row["Source Listing Price"] = truncate_text(listing.price, 80)
                row["Source Listing Description"] = truncate_text(clean_source_listing_description(listing.description), 700)
                row["Source Listing Detail Preview"] = build_source_detail_preview(listing.description, listing.details_text)
                row["Detected Book Count"] = str(book_count or "")
                row["Book Count Evidence"] = evidence
                row["Book Count Status"] = book_count_status
                row["Book Count Exclusion Limit"] = str(config.max_book_count_for_export or "")
                row = apply_reference_count_result_to_row(row, reference_count_result)
                row["Estimated Book Weight g"] = str(book_weight_estimate.weight_g if book_count else "")
                row["Book Weight Evidence"] = book_weight_estimate.evidence if book_count else ""
                row["Estimated Packaging Weight kg"] = f"{packaging_estimate.weight_kg:.3f}" if book_count else ""
                row["Packaging Materials"] = packaging_estimate.materials if book_count else ""
                row["Packaging Weight Evidence"] = packaging_estimate.evidence if book_count else ""
                row["Estimated Weight kg"] = f"{weight_kg:.3f}" if weight_kg else ""
                row["Estimated Actual Weight kg"] = f"{weight_kg:.3f}" if weight_kg else ""
                row["Dimensional Weight kg"] = f"{dimensional_weight_kg:.3f}" if dimensional_weight_kg else ""
                row["Billable Weight kg"] = f"{billable_weight_kg:.3f}" if billable_weight_kg else ""
                row["Billable Weight Source"] = billable_weight_source
                row["Package Length cm"] = f"{package_length_cm:.1f}" if package_length_cm else ""
                row["Package Width cm"] = f"{package_width_cm:.1f}" if package_width_cm else ""
                row["Package Height cm"] = f"{package_height_cm:.1f}" if package_height_cm else ""
                row["Package Dimension Source"] = package_dimension_source
                row["Dimensional Divisor"] = str(config.dimensional_divisor_cm)
                row["FICP Zone"] = config.zone
                row["FICP US Zone"] = ficp_us_zone_label(config.zone)
                row["FICP Billed Weight kg"] = f"{ficp_charge.billed_weight_kg:.3f}" if ficp_charge else ""
                row["FICP Base Shipping JPY"] = str(ficp_charge.shipping_jpy) if ficp_charge else ""
                row["FICP Base Shipping USD"] = f"{base_shipping_usd:.2f}" if base_shipping_usd is not None else ""
                row["FICP Fuel Surcharge Percent"] = f"{config.fuel_surcharge_percent:.2f}" if ficp_charge else ""
                row["FICP Fuel Surcharge JPY"] = str(fuel_surcharge_jpy) if fuel_surcharge_jpy is not None else ""
                row["FICP Fuel Surcharge USD"] = f"{fuel_surcharge_usd:.2f}" if fuel_surcharge_usd is not None else ""
                row["FICP Shipping JPY"] = str(total_shipping_jpy) if total_shipping_jpy is not None else ""
                row["FICP Shipping USD"] = f"{shipping_usd:.2f}" if shipping_usd is not None else ""
                row["FICP Shipping Includes Fuel Surcharge"] = "Yes" if ficp_charge and config.fuel_surcharge_percent > 0 else "No" if ficp_charge else ""
                row["Listing Eligibility"] = "Excluded"
                row["Exclusion Reason"] = count_limit_exclusion.reason
                row["Exclusion Evidence"] = count_limit_exclusion.evidence
                row["USDJPY Exchange Rate"] = f"{config.exchange_rate_jpy_per_usd:.4f}"
                row["USDJPY Exchange Rate Source"] = config.exchange_rate_source
                row["USDJPY Exchange Rate Date"] = config.exchange_rate_date
                row["Scrape Status"] = f"excluded: {listing.status}"
                row["Main Image URL"] = image_url
                row["AI Enrichment Status"] = "skipped: excluded"
                row["Description Added Text"] = (
                    "Excluded from export CSV: detected book count exceeds the configured maximum."
                )
                row["Description Added Japanese"] = (
                    "出品除外: 判定された冊数が設定した最大冊数を超えているため、ダウンロードCSVから除外します。"
                )
                row["Description Detail Notes"] = (
                    f"Excluded from export CSV: {count_limit_exclusion.reason}; "
                    f"evidence: {count_limit_exclusion.evidence}"
                )
                row = apply_processing_diagnostics(row)
                output.loc[index, row.index] = row
                if progress_callback:
                    progress_callback(position, total, f"excluded: {title or f'row {index + 1}'}")
                if config.enable_scrape and config.request_delay_seconds > 0 and position < total:
                    time.sleep(config.request_delay_seconds)
                continue

            specifics = infer_specifics_with_notes(
                title,
                combined_text,
                candidate_columns=specific_columns,
                book_count=book_count,
                weight_kg=weight_kg,
                book_count_evidence=evidence,
                enable_reference_lookup=config.enable_reference_lookup,
                condition_text=condition_evidence_text,
            )
            if ai_enrichment.status == "disabled" and config.enable_ai_enrichment:
                ai_enrichment = enrich_listing_with_ai(
                    config=config,
                    title=title,
                    description=listing.description,
                    details_text=listing.details_text,
                    candidate_columns=specific_columns,
                    book_count=book_count,
                )
            merge_ai_specifics(specifics, ai_enrichment, specific_columns)
            row, specifics_cleanup_notes = clear_non_english_specific_values(row, specific_columns)
            original_specifics_row = row.copy()
            row, specifics_fill_notes = apply_item_specifics_with_report(row, specifics.values, target_columns=specific_columns)
            specifics_summary = build_specifics_application_summary(original_specifics_row, row, specifics.values, specific_columns)

            if config.title_col and is_blank(row.get(config.title_col, "")) and title:
                row[config.title_col] = title
            if config.image_col and image_url and not contains_likely_image_url(row.get(config.image_col, "")):
                row[config.image_col] = image_url
            if config.price_col and is_blank(row.get(config.price_col, "")) and price:
                row[config.price_col] = price
            if config.description_col:
                buyer_detail_notes = extract_buyer_relevant_listing_details(
                    listing.description,
                    listing.details_text,
                )
                buyer_detail_notes = append_unique_buyer_notes(buyer_detail_notes, ai_enrichment.description_notes)
                addition = build_description_append(
                    title=title,
                    book_count=book_count,
                    evidence=evidence,
                    weight_kg=weight_kg,
                    ficp_charge=ficp_charge,
                    shipping_usd=shipping_usd,
                    source_url=source_url,
                    buyer_detail_notes=buyer_detail_notes,
                )
                row[config.description_col] = append_description(csv_description, addition)
                description_added_text = build_description_append_display_text(addition)
                row["Description Added Text"] = description_added_text
                row["Description Added Japanese"] = translate_description_added_text_to_japanese(description_added_text)
                row["Description Added HTML"] = addition
                row["Description Detail Notes"] = build_description_detail_summary(
                    book_count=book_count,
                    evidence=evidence,
                    buyer_detail_notes=buyer_detail_notes,
                    addition=addition,
                )
            if config.shipping_col and shipping_usd is not None:
                row[config.shipping_col] = f"{shipping_usd:.2f}"

            row["Inferred Source URL"] = inferred_source.url
            row["Source URL Confidence"] = source_confidence
            row["Source URL Evidence"] = source_evidence
            row["Source Listing Title"] = truncate_text(listing.title, 300)
            row["Source Listing Price"] = truncate_text(listing.price, 80)
            row["Source Listing Description"] = truncate_text(clean_source_listing_description(listing.description), 700)
            row["Source Listing Detail Preview"] = build_source_detail_preview(listing.description, listing.details_text)
            row["Detected Book Count"] = str(book_count or "")
            row["Book Count Evidence"] = evidence
            row["Book Count Status"] = book_count_status
            row["Book Count Exclusion Limit"] = str(config.max_book_count_for_export or "")
            row = apply_reference_count_result_to_row(row, reference_count_result)
            row["Estimated Book Weight g"] = str(book_weight_estimate.weight_g if book_count else "")
            row["Book Weight Evidence"] = book_weight_estimate.evidence if book_count else ""
            row["Estimated Packaging Weight kg"] = f"{packaging_estimate.weight_kg:.3f}" if book_count else ""
            row["Packaging Materials"] = packaging_estimate.materials if book_count else ""
            row["Packaging Weight Evidence"] = packaging_estimate.evidence if book_count else ""
            row["Estimated Weight kg"] = f"{weight_kg:.3f}" if weight_kg else ""
            row["Estimated Actual Weight kg"] = f"{weight_kg:.3f}" if weight_kg else ""
            row["Dimensional Weight kg"] = f"{dimensional_weight_kg:.3f}" if dimensional_weight_kg else ""
            row["Billable Weight kg"] = f"{billable_weight_kg:.3f}" if billable_weight_kg else ""
            row["Billable Weight Source"] = billable_weight_source
            row["Package Length cm"] = f"{package_length_cm:.1f}" if package_length_cm else ""
            row["Package Width cm"] = f"{package_width_cm:.1f}" if package_width_cm else ""
            row["Package Height cm"] = f"{package_height_cm:.1f}" if package_height_cm else ""
            row["Package Dimension Source"] = package_dimension_source
            row["Dimensional Divisor"] = str(config.dimensional_divisor_cm)
            row["FICP Zone"] = config.zone
            row["FICP US Zone"] = ficp_us_zone_label(config.zone)
            row["FICP Billed Weight kg"] = f"{ficp_charge.billed_weight_kg:.3f}" if ficp_charge else ""
            row["FICP Base Shipping JPY"] = str(ficp_charge.shipping_jpy) if ficp_charge else ""
            row["FICP Base Shipping USD"] = f"{base_shipping_usd:.2f}" if base_shipping_usd is not None else ""
            row["FICP Fuel Surcharge Percent"] = f"{config.fuel_surcharge_percent:.2f}" if ficp_charge else ""
            row["FICP Fuel Surcharge JPY"] = str(fuel_surcharge_jpy) if fuel_surcharge_jpy is not None else ""
            row["FICP Fuel Surcharge USD"] = f"{fuel_surcharge_usd:.2f}" if fuel_surcharge_usd is not None else ""
            row["FICP Shipping JPY"] = str(total_shipping_jpy) if total_shipping_jpy is not None else ""
            row["FICP Shipping USD"] = f"{shipping_usd:.2f}" if shipping_usd is not None else ""
            row["FICP Shipping Includes Fuel Surcharge"] = "Yes" if ficp_charge and config.fuel_surcharge_percent > 0 else "No" if ficp_charge else ""
            row["Listing Eligibility"] = "OK"
            row["Exclusion Reason"] = ""
            row["Exclusion Evidence"] = ""
            row["USDJPY Exchange Rate"] = f"{config.exchange_rate_jpy_per_usd:.4f}"
            row["USDJPY Exchange Rate Source"] = config.exchange_rate_source
            row["USDJPY Exchange Rate Date"] = config.exchange_rate_date
            row["Scrape Status"] = listing.status
            row["Main Image URL"] = image_url
            row["AI Provider"] = ai_enrichment.provider
            row["AI Model"] = ai_enrichment.model
            row["AI Enrichment Status"] = ai_enrichment.status
            row["AI Description Notes"] = "; ".join(ai_enrichment.description_notes)
            row["AI Specifics Suggestions"] = format_specifics_field_map(ai_enrichment.specifics)
            row["Specifics Fill Notes"] = "; ".join(specifics_cleanup_notes + specifics_fill_notes + specifics.notes)
            row["Specifics Filled Fields"] = format_specifics_field_map(specifics_summary["filled"])
            row["Specifics Existing Fields"] = format_specifics_field_map(specifics_summary["existing"])
            row["Specifics Not Filled Fields"] = format_specifics_field_map(specifics_summary["not_filled"])

            row = apply_processing_diagnostics(row)
            output.loc[index, row.index] = row
            if progress_callback:
                progress_callback(position, total, title or f"row {index + 1}")
            if config.enable_scrape and config.request_delay_seconds > 0 and position < total:
                time.sleep(config.request_delay_seconds)
    finally:
        if browser_scraper is not None:
            browser_scraper.close()

    return output.fillna("")


def get_row_value(row: pd.Series, column: str) -> str:
    if not column or column not in row.index:
        return ""
    return str(row.get(column, "") or "").strip()


def load_streamlit():
    try:
        import streamlit as st
    except ImportError as error:  # pragma: no cover - only triggered at runtime.
        raise SystemExit(
            "Streamlit is not installed. Run: python -m pip install -r requirements-streamlit.txt"
        ) from error
    return st


def save_uploaded_csv_cache(raw: bytes, file_name: str) -> None:
    if is_public_mode():
        return
    try:
        UPLOAD_CACHE_RAW_PATH.parent.mkdir(parents=True, exist_ok=True)
        UPLOAD_CACHE_RAW_PATH.write_bytes(raw)
        UPLOAD_CACHE_META_PATH.write_text(
            json.dumps(
                {
                    "file_name": file_name,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "saved_at": time.time(),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except OSError:
        return


def load_uploaded_csv_cache() -> tuple[bytes, str]:
    if is_public_mode():
        return b"", ""
    try:
        raw = UPLOAD_CACHE_RAW_PATH.read_bytes()
        metadata = json.loads(UPLOAD_CACHE_META_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return b"", ""

    expected_hash = str(metadata.get("sha256") or "")
    if expected_hash and hashlib.sha256(raw).hexdigest() != expected_hash:
        return b"", ""
    file_name = str(metadata.get("file_name") or "uploaded.csv")
    return raw, file_name


def save_processed_dataframe_cache(frame: pd.DataFrame, file_key: str) -> None:
    if is_public_mode():
        return
    try:
        PROCESSED_CACHE_DF_PATH.parent.mkdir(parents=True, exist_ok=True)
        frame.to_pickle(PROCESSED_CACHE_DF_PATH)
        PROCESSED_CACHE_META_PATH.write_text(
            json.dumps(
                {
                    "file_key": file_key,
                    "row_count": int(len(frame)),
                    "saved_at": time.time(),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except (OSError, ValueError, TypeError):
        return


def load_processed_dataframe_cache(file_key: str) -> Optional[pd.DataFrame]:
    if is_public_mode():
        return None
    try:
        metadata = json.loads(PROCESSED_CACHE_META_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if str(metadata.get("file_key") or "") != file_key:
        return None
    try:
        frame = pd.read_pickle(PROCESSED_CACHE_DF_PATH)
    except (OSError, ValueError, TypeError, AttributeError, ImportError):
        return None
    if not isinstance(frame, pd.DataFrame):
        return None
    return frame


def has_product_select_query(st) -> bool:
    try:
        return st.query_params.get("comic_ficp_select") is not None
    except Exception:
        return False


def get_uploaded_or_cached_csv(st, uploaded, persist: bool = True) -> tuple[bytes, str, bool]:
    cache_raw_key = "comic_ficp_uploaded_raw"
    cache_name_key = "comic_ficp_uploaded_name"

    if uploaded is not None:
        raw = uploaded.getvalue()
        file_name = getattr(uploaded, "name", "uploaded.csv") or "uploaded.csv"
        st.session_state[cache_raw_key] = raw
        st.session_state[cache_name_key] = file_name
        if persist and raw:
            save_uploaded_csv_cache(raw, file_name)
        return raw, file_name, False

    cached_raw = st.session_state.get(cache_raw_key)
    if isinstance(cached_raw, str):
        cached_raw = cached_raw.encode("utf-8")
    if cached_raw:
        cached_name = st.session_state.get(cache_name_key, "uploaded.csv") or "uploaded.csv"
        return bytes(cached_raw), str(cached_name), True

    if persist and has_product_select_query(st):
        disk_raw, disk_name = load_uploaded_csv_cache()
        if disk_raw:
            st.session_state[cache_raw_key] = disk_raw
            st.session_state[cache_name_key] = disk_name
            return disk_raw, disk_name, True

    return b"", "", False


def main() -> None:  # pragma: no cover - UI smoke-tested manually.
    st = load_streamlit()
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    render_global_styles(st)
    st.markdown(
        """
        <div class="app-header">
          <div>
            <div class="app-kicker">eBay listing CSV</div>
            <h1>漫画セット補完ワークベンチ</h1>
          </div>
          <div class="header-badge">Mercari details / Specifics / FICP</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    render_public_login_gate(st)

    uploaded = st.file_uploader("1. CSVファイル", type=["csv"], label_visibility="collapsed")
    raw, uploaded_name, using_cached_upload = get_uploaded_or_cached_csv(st, uploaded, persist=not is_public_mode())

    if not raw:
        st.markdown(
            """
            <div class="empty-state">
              <h3>CSVをここに読み込んで開始</h3>
              <p>読み込み後、列の対応、米国向け送料設定、商品ごとの確認を同じ画面で行えます。</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    if using_cached_upload:
        st.caption(f"前回読み込んだCSVを保持しています: {uploaded_name}")

    file_key = f"{uploaded_name}:{hashlib.sha256(raw).hexdigest()}"
    frame, encoding = read_csv_bytes(raw)
    headers = list(frame.columns)
    guessed = guess_columns(headers)
    options = [""] + headers

    restore_processed_cache = using_cached_upload or has_product_select_query(st)
    active_frame = st.session_state.get("comic_ficp_processed_df")
    if active_frame is None or st.session_state.get("comic_ficp_file_key") != file_key:
        cached_processed_frame = load_processed_dataframe_cache(file_key) if restore_processed_cache else None
        active_frame = cached_processed_frame if cached_processed_frame is not None else frame
        st.session_state["comic_ficp_processed_df"] = active_frame
        st.session_state["comic_ficp_file_key"] = file_key

    row_options = list(range(len(active_frame)))
    if not row_options:
        st.warning("CSVに行がありません。")
        return
    selected_index_key = "comic_ficp_selected_index"
    view_key = "comic_ficp_workspace_view"
    if selected_index_key not in st.session_state or st.session_state[selected_index_key] not in row_options:
        st.session_state[selected_index_key] = row_options[0]
    if view_key not in st.session_state:
        st.session_state[view_key] = "選択商品"
    apply_query_selected_row(st, row_options, selected_index_key, view_key)

    render_file_summary(st, uploaded_name, len(frame), encoding, active_frame)
    selected_title_col = st.session_state.get("comic_ficp_title_col", guessed["title_col"])

    selected_index = st.selectbox(
        "2. 確認・処理する商品",
        row_options,
        format_func=lambda idx: format_row_label(active_frame.iloc[idx], idx, selected_title_col),
        key=selected_index_key,
    )

    control_col, workspace_col = st.columns([0.32, 0.68], gap="medium")
    with control_col:
        url_col = guessed["url_col"] if guessed["url_col"] in options else ""
        image_col = guessed["image_col"] if guessed["image_col"] in options else ""
        title_col = guessed["title_col"] if guessed["title_col"] in options else ""
        price_col = guessed["price_col"] if guessed["price_col"] in options else ""
        description_col = guessed["description_col"] if guessed["description_col"] in options else ""
        shipping_col = guessed["shipping_col"] if guessed["shipping_col"] in options else ""
        shipping_profile_col = guessed["shipping_profile_col"] if guessed.get("shipping_profile_col") in options else ""
        st.markdown('<div class="section-title">3. 自動判定されたCSV列</div>', unsafe_allow_html=True)
        render_mapping_status(st, url_col, image_col, title_col, description_col, shipping_profile_col, shipping_col)
        with st.expander("CSV列の対応を手動で変更する"):
            st.caption("通常は自動判定のままでOKです。別形式のCSVや判定ミスがある場合だけ変更してください。")
            url_col = st.selectbox(
                "参照元URLまたは商品ID入り画像URL",
                options,
                index=options.index(url_col) if url_col in options else 0,
            )
            image_col = st.selectbox("画像URL", options, index=options.index(image_col) if image_col in options else 0)
            title_col = st.selectbox(
                "タイトル",
                options,
                index=options.index(title_col) if title_col in options else 0,
                key="comic_ficp_title_col",
            )
            price_col = st.selectbox("価格", options, index=options.index(price_col) if price_col in options else 0)
            description_col = st.selectbox(
                "Description",
                options,
                index=options.index(description_col) if description_col in options else 0,
            )
            shipping_profile_col = st.selectbox(
                "配送ポリシー列",
                options,
                index=options.index(shipping_profile_col) if shipping_profile_col in options else 0,
            )
            shipping_col = st.selectbox(
                "送料額列（通常未使用）",
                options,
                index=options.index(shipping_col) if shipping_col in options else 0,
                help="eBayのポリシーCSVでは通常は空欄のままでOKです。ShippingProfileNameはここに選ばないでください。",
            )
            render_mapping_status(st, url_col, image_col, title_col, description_col, shipping_profile_col, shipping_col)

        st.markdown('<div class="section-title">4. 送料と取得</div>', unsafe_allow_html=True)
        with st.container(border=True):
            zone = st.selectbox(
                "米国向けFICP Zone",
                FICP_ZONES,
                index=FICP_ZONES.index(DEFAULT_FICP_ZONE),
                format_func=lambda value: ZONE_LABELS.get(value, value),
            )
            set_col1, set_col2 = st.columns(2)
            book_weight_g = set_col1.number_input(
                "判定不能時の1冊重量(g)",
                min_value=80,
                max_value=500,
                value=DEFAULT_BOOK_WEIGHT_G,
                step=10,
                key="fallback_book_weight_g_v2",
                help="タイトルや商品情報から判型を推定できない場合だけ使う予備値です。",
            )
            packaging_weight_kg = set_col2.number_input(
                "予備の梱包重量(kg)",
                min_value=0.0,
                max_value=5.0,
                value=DEFAULT_PACKAGING_WEIGHT_KG,
                step=0.05,
                key="fallback_packaging_weight_kg_v2",
                help="通常は商品ごとに自動推定します。冊数が取れないなど推定できない場合の予備値です。",
            )
            st.caption("1冊重量は商品ごとに自動推定します。例: ジャンプ系は約180g、ヤンマガ/青年B6系は約220g、完全版/愛蔵版は約320g。")
            st.caption("梱包材も商品ごとに自動推定します。基本はプチプチ、段ボール、隙間埋め紙材を想定し、多冊セットほど重めに見ます。")
            st.caption("FedExは実重量と容積重量の大きい方を課金重量として使います。箱サイズは冊数から自動で概算します。")
            max_book_count_for_export = st.number_input(
                "除外する最大冊数（0で無効）",
                min_value=0,
                max_value=300,
                value=DEFAULT_MAX_BOOK_COUNT_FOR_EXPORT,
                step=1,
                help="例: 40にすると、41冊以上と判定された商品は出品CSVから自動除外します。",
            )
            if max_book_count_for_export:
                st.caption(f"{int(max_book_count_for_export)}冊を超える商品は、除外候補に入り、ダウンロードCSVから外れます。")
            else:
                st.caption("冊数による除外は無効です。欠巻・欠品などの危険文言による除外は従来どおり動作します。")
            package_length_cm = 0.0
            package_width_cm = 0.0
            package_height_cm = 0.0
            dimensional_divisor = DEFAULT_DIMENSIONAL_DIVISOR_CM

            selected_row_for_dimensions = active_frame.iloc[selected_index]
            selected_dimension_text = " ".join(
                [
                    get_row_value(selected_row_for_dimensions, title_col),
                    get_row_value(selected_row_for_dimensions, description_col),
                    get_row_value(selected_row_for_dimensions, "Book Count Evidence"),
                ]
            )
            selected_detected_count = parse_float_text(get_row_value(selected_row_for_dimensions, "Detected Book Count"))
            selected_book_count = int(selected_detected_count) if selected_detected_count and selected_detected_count.is_integer() else None
            selected_count_evidence = get_row_value(selected_row_for_dimensions, "Book Count Evidence")
            if not selected_book_count:
                selected_book_count, selected_count_evidence = detect_book_count(selected_dimension_text)
            selected_weight_text = " ".join(
                [
                    selected_dimension_text,
                    get_row_value(selected_row_for_dimensions, "Source Listing Title"),
                    get_row_value(selected_row_for_dimensions, "Source Listing Description"),
                    get_row_value(selected_row_for_dimensions, "Source Listing Detail Preview"),
                    get_row_value(selected_row_for_dimensions, "C:Publisher"),
                    get_row_value(selected_row_for_dimensions, "C:Genre"),
                    get_row_value(selected_row_for_dimensions, "C:Format"),
                ]
            )
            selected_book_weight_estimate = estimate_book_weight_g(selected_weight_text, book_weight_g)
            estimated_length, estimated_width, estimated_height = estimate_package_dimensions_cm(selected_book_count)
            if selected_book_count and all(value > 0 for value in (estimated_length, estimated_width, estimated_height)):
                selected_packaging_estimate = estimate_packaging_weight_kg(
                    selected_book_count,
                    estimated_length,
                    estimated_width,
                    estimated_height,
                    packaging_weight_kg,
                )
                selected_actual_weight = calculate_weight_kg(
                    selected_book_count,
                    selected_book_weight_estimate.weight_g,
                    selected_packaging_estimate.weight_kg,
                )
                estimated_dimensional_weight = calculate_dimensional_weight_kg(
                    estimated_length,
                    estimated_width,
                    estimated_height,
                    DEFAULT_DIMENSIONAL_DIVISOR_CM,
                )
                st.info(
                    f"選択商品の推定1冊重量: {selected_book_weight_estimate.weight_g}g "
                    f"（{selected_book_weight_estimate.evidence}）\n\n"
                    f"推定梱包重量: {selected_packaging_estimate.weight_kg:.3f} kg "
                    f"（{selected_packaging_estimate.materials} / {selected_packaging_estimate.evidence}）\n\n"
                    f"実重量 約{selected_actual_weight:.3f} kg\n\n"
                    f"選択商品の概算箱サイズ: {estimated_length:.1f} x {estimated_width:.1f} x {estimated_height:.1f} cm "
                    f"/ 容積重量 約{estimated_dimensional_weight:.3f} kg "
                    f"（{selected_book_count}冊から概算）"
                )
                if selected_count_evidence:
                    st.caption(f"冊数の根拠: {selected_count_evidence}")
            else:
                st.info("箱サイズは、処理時に判定できた冊数から自動で概算します。冊数が判定できない行だけ箱サイズなしで計算します。")

            with st.expander("箱サイズを手動で上書きする", expanded=False):
                st.caption("通常は変更不要です。実際の梱包箱サイズが分かっている場合だけ入力してください。")
                dim_col1, dim_col2, dim_col3, dim_col4 = st.columns(4)
                package_length_cm = dim_col1.number_input("箱 長さ(cm)", min_value=0.0, max_value=200.0, value=0.0, step=0.5)
                package_width_cm = dim_col2.number_input("箱 幅(cm)", min_value=0.0, max_value=200.0, value=0.0, step=0.5)
                package_height_cm = dim_col3.number_input("箱 高さ(cm)", min_value=0.0, max_value=200.0, value=0.0, step=0.5)
                dimensional_divisor = dim_col4.number_input(
                    "容積係数", min_value=1000, max_value=10000, value=DEFAULT_DIMENSIONAL_DIVISOR_CM, step=100
                )
            if "usd_jpy_exchange_rate" not in st.session_state:
                latest_rate = fetch_usd_jpy_exchange_rate()
                st.session_state["usd_jpy_exchange_rate"] = latest_rate.rate
                st.session_state["usd_jpy_exchange_rate_source"] = latest_rate.source
                st.session_state["usd_jpy_exchange_rate_date"] = latest_rate.date
                st.session_state["usd_jpy_exchange_rate_status"] = latest_rate.status

            rate_col1, rate_col2 = st.columns([0.68, 0.32])
            exchange_rate = rate_col1.number_input(
                "USD換算レート(JPY/USD)",
                min_value=1.0,
                max_value=500.0,
                value=float(st.session_state.get("usd_jpy_exchange_rate", DEFAULT_EXCHANGE_RATE_JPY_PER_USD)),
                step=0.1,
                key="usd_jpy_exchange_rate",
            )
            if rate_col2.button("最新レート取得", use_container_width=True):
                latest_rate = fetch_usd_jpy_exchange_rate()
                st.session_state["usd_jpy_exchange_rate"] = latest_rate.rate
                st.session_state["usd_jpy_exchange_rate_source"] = latest_rate.source
                st.session_state["usd_jpy_exchange_rate_date"] = latest_rate.date
                st.session_state["usd_jpy_exchange_rate_status"] = latest_rate.status
                st.rerun()
            exchange_rate_source = str(st.session_state.get("usd_jpy_exchange_rate_source", "manual/default"))
            exchange_rate_date = str(st.session_state.get("usd_jpy_exchange_rate_date", ""))
            exchange_rate_status = str(st.session_state.get("usd_jpy_exchange_rate_status", "manual/default"))
            st.caption(
                f"USD/JPY: {float(exchange_rate):.4f} / 取得元: {exchange_rate_source}"
                + (f" / 日付: {exchange_rate_date}" if exchange_rate_date else "")
                + ("" if exchange_rate_status == "ok" else f" / 状態: {exchange_rate_status}")
            )
            fuel_surcharge_percent = st.number_input(
                "FedEx燃油サーチャージ(%)",
                min_value=0.0,
                max_value=100.0,
                value=float(st.session_state.get("fuel_surcharge_percent", DEFAULT_FUEL_SURCHARGE_PERCENT)),
                step=0.25,
                key="fuel_surcharge_percent",
            )
            st.caption("FICP基本送料にこの率を掛けた燃油分を加算し、CSVの送料欄には燃油込みのUSDを入力します。")
            enable_scrape = st.checkbox("公開ページを取得", value=True)
            enable_browser_scrape = st.checkbox("メルカリ説明欄をブラウザ描画で取得", value=True)
            enable_reference_lookup = st.checkbox("無料リファレンス検索でSpecificsを補強", value=True)
            enable_ai_enrichment = st.checkbox(
                "AI補完を使う（OpenAI/Gemini API・有料の場合あり）",
                value=True,
                key="enable_ai_enrichment_default_on",
            )
            ai_provider = DEFAULT_AI_PROVIDER
            ai_model = DEFAULT_GEMINI_MODEL
            ai_api_key = ""
            if enable_ai_enrichment:
                provider_label = st.selectbox(
                    "AIプロバイダー",
                    ["Gemini", "OpenAI"],
                    index=0,
                    help="Gemini Flash系は低コスト向き、OpenAIは文章の安定性を重視したい時向きです。",
                )
                ai_provider = "gemini" if provider_label == "Gemini" else "openai"
                model_options = ai_model_options_for_provider(ai_provider)
                model_ids = [model_id for model_id, _ in model_options]
                model_labels = {model_id: label for model_id, label in model_options}
                default_ai_model = default_ai_model_for_provider(ai_provider)
                default_model_index = model_ids.index(default_ai_model) if default_ai_model in model_ids else 0
                selected_ai_model = st.selectbox(
                    "AIモデル",
                    model_ids,
                    index=default_model_index,
                    format_func=lambda model_id: model_labels.get(model_id, model_id),
                    help="一覧にないモデルはカスタム入力を選んでください。",
                )
                if selected_ai_model == "custom":
                    ai_model = st.text_input(
                        "カスタムAIモデル名",
                        value=default_ai_model,
                        help="例: gemini-2.5-flash-lite / gpt-5.4-mini",
                    )
                else:
                    ai_model = selected_ai_model
                if is_public_mode():
                    public_user = current_public_user(st)
                    saved_exists = bool(
                        public_user and public_saved_api_key_exists(public_user["id"], ai_provider, public_database_url())
                    )
                    use_saved_key = False
                    if saved_exists:
                        use_saved_key = st.checkbox(
                            "保存済みキーを使う",
                            value=True,
                            key=f"use_public_saved_api_key_{ai_provider}",
                            help="保存済みキーは画面に表示せず、処理時だけ暗号化DBから読み込みます。",
                        )
                        if use_saved_key and public_user:
                            ai_api_key = load_public_saved_api_key(public_user["id"], ai_provider, public_database_url())
                    st.caption("公開版では、APIキーはユーザー別にサーバーDBへ暗号化保存されます。CSVや処理ログには出力しません。")
                    new_api_key = st.text_input(
                        "新しいAPIキーを保存する",
                        value="",
                        type="password",
                        key=f"public_ai_api_key_input_{ai_provider}",
                        help="入力したキーは保存ボタンを押した場合だけ暗号化保存されます。",
                    )
                    key_save_col, key_delete_col = st.columns(2)
                    if key_save_col.button(
                        "APIキーを保存",
                        use_container_width=True,
                        disabled=not bool(new_api_key.strip()) or not bool(public_user),
                    ):
                        saved, message = save_public_api_key(
                            public_user["id"],
                            ai_provider,
                            new_api_key,
                            public_database_url(),
                        )
                        if saved:
                            st.success(message)
                            st.session_state.pop(f"public_ai_api_key_input_{ai_provider}", None)
                            st.rerun()
                        else:
                            st.warning(message)
                    if key_delete_col.button(
                        "保存済みキーを削除",
                        use_container_width=True,
                        disabled=not saved_exists or not bool(public_user),
                    ):
                        deleted, message = delete_public_saved_api_key(public_user["id"], ai_provider, public_database_url())
                        if deleted:
                            st.success(message)
                            st.rerun()
                        else:
                            st.warning(message)
                    if saved_exists and use_saved_key and ai_api_key:
                        st.caption("保存済みAPIキーを使用します。キー文字列は画面に表示しません。")
                    elif enable_ai_enrichment:
                        st.caption("保存済みキーがない場合、AI補完はAPIキー入力・保存後に利用できます。通常の取得や送料計算は続行できます。")
                else:
                    saved_ai_api_key = load_saved_api_key(ai_provider) if api_key_storage_available() else ""
                    ai_api_key = st.text_input(
                        "APIキー",
                        value=saved_ai_api_key,
                        type="password",
                        key=f"ai_api_key_input_{ai_provider}",
                        help="この値はCSVやログには保存しません。保存ボタンを押した場合のみ、このPCのWindowsユーザー暗号化領域に保存します。",
                    )
                    key_save_col, key_delete_col = st.columns(2)
                    if key_save_col.button("APIキーを保存", use_container_width=True, disabled=not bool(ai_api_key.strip())):
                        saved, message = save_api_key(ai_provider, ai_api_key)
                        if saved:
                            st.success(message)
                        else:
                            st.warning(message)
                    if key_delete_col.button(
                        "保存済みキーを削除",
                        use_container_width=True,
                        disabled=not saved_api_key_exists(ai_provider),
                    ):
                        deleted, message = delete_saved_api_key(ai_provider)
                        if deleted:
                            st.success(message)
                            st.session_state.pop(f"ai_api_key_input_{ai_provider}", None)
                            st.rerun()
                        else:
                            st.warning(message)
                    if saved_ai_api_key:
                        st.caption("保存済みAPIキーを読み込みました。このキーはCSVやログには出力しません。")
                    elif api_key_storage_available():
                        st.caption("APIキーを保存すると、次回から同じプロバイダー選択時に自動入力されます。")
                    else:
                        st.caption("この環境ではAPIキー保存は利用できません。通常入力のみ使えます。")
                st.caption("モデルによって料金・速度・利用可否が変わります。Pro/Preview系は契約やAPI権限で使えない場合があります。")
                st.caption("AIはSpecifics候補とDescription追記の補強だけに使います。送料・重量・FedEx計算は従来ロジックで処理します。")
            else:
                st.caption("メルカリの説明欄・商品状態はChrome取得とルール処理で補完します。AI/API補完はOFFです。")
            with st.expander("取得が不安定なときの調整", expanded=False):
                request_delay = st.slider(
                    "連続処理の待ち時間(秒)",
                    min_value=0.0,
                    max_value=2.0,
                    value=0.5,
                    step=0.1,
                    help="複数商品をまとめて処理するとき、次の商品へ進む前に少し待つ時間です。通常は変更不要です。",
                )
                st.caption("大量処理で取得失敗が増える場合だけ、0.8〜1.0秒程度へ上げてください。")

        config = ProcessingConfig(
            url_col=url_col,
            image_col=image_col,
            title_col=title_col,
            price_col=price_col,
            description_col=description_col,
            shipping_col=shipping_col,
            zone=zone,
            book_weight_g=int(book_weight_g),
            packaging_weight_kg=float(packaging_weight_kg),
            max_book_count_for_export=int(max_book_count_for_export),
            exchange_rate_jpy_per_usd=float(exchange_rate),
            exchange_rate_source=exchange_rate_source,
            exchange_rate_date=exchange_rate_date,
            fuel_surcharge_percent=float(fuel_surcharge_percent),
            enable_scrape=enable_scrape,
            enable_browser_scrape=enable_browser_scrape,
            enable_reference_lookup=enable_reference_lookup,
            request_delay_seconds=float(request_delay),
            package_length_cm=float(package_length_cm),
            package_width_cm=float(package_width_cm),
            package_height_cm=float(package_height_cm),
            dimensional_divisor_cm=int(dimensional_divisor),
            enable_ai_enrichment=enable_ai_enrichment,
            ai_provider=ai_provider,
            ai_model=ai_model,
            ai_api_key=ai_api_key,
        )

        st.markdown('<div class="section-title">5. 実行と保存</div>', unsafe_allow_html=True)
        with st.container(border=True):
            rollup_enabled = st.checkbox("送料を価格に転嫁して送料無料にする", value=True)
            free_shipping_profile_name = st.selectbox(
                "送料無料ポリシー名",
                FREE_SHIPPING_PROFILE_OPTIONS,
                index=FREE_SHIPPING_PROFILE_OPTIONS.index(DEFAULT_FREE_SHIPPING_PROFILE_NAME),
                disabled=not rollup_enabled,
            )
            transfer_markup_percent = st.number_input(
                "安全上乗せ率(%)",
                min_value=0.0,
                max_value=50.0,
                value=DEFAULT_FREE_SHIPPING_MARKUP_PERCENT,
                step=0.5,
                disabled=not rollup_enabled,
            )
            if rollup_enabled:
                st.caption("ダウンロードCSVでのみ、FICP送料合計に上乗せ率を掛けた金額をStartPriceへ加算し、配送ポリシーを送料無料にします。")
            rollup_options = FreeShippingRollupOptions(
                enabled=rollup_enabled,
                price_col=price_col,
                shipping_profile_col=shipping_profile_col or "ShippingProfileName",
                free_shipping_profile_name=free_shipping_profile_name,
                markup_percent=float(transfer_markup_percent),
            )
            process_selected = st.button("選択行を処理", type="primary", use_container_width=True)
            process_all = st.button("全件を処理", type="secondary", use_container_width=True)
            clear_results = st.button("処理前に戻す", use_container_width=True)
            feedback_slot = st.empty()
            download_slot = st.empty()

    if clear_results:
        st.session_state["comic_ficp_processed_df"] = frame
        active_frame = frame
        save_processed_dataframe_cache(active_frame, file_key)

    if process_selected or process_all:
        indices = [selected_index] if process_selected else list(active_frame.index)
        with feedback_slot.container():
            progress_bar = st.progress(0)
            progress_text = st.empty()

        def progress(current: int, total: int, label: str) -> None:
            progress_bar.progress(current / total)
            progress_text.write(f"{current}/{total}: {label[:90]}")

        with st.spinner("処理中です"):
            active_frame = process_dataframe(active_frame, config, row_indices=indices, progress_callback=progress)
            st.session_state["comic_ficp_processed_df"] = active_frame
            save_processed_dataframe_cache(active_frame, file_key)
        with feedback_slot.container():
            st.success("処理が完了しました。")

    export_frame = build_export_dataframe(active_frame, rollup_options)
    excluded_count = len(active_frame) - len(export_frame)
    output_name = f"ebay-comic-ficp-{time.strftime('%Y%m%d-%H%M%S')}.csv"
    with download_slot:
        if excluded_count:
            st.warning(f"出品除外 {excluded_count} 件は、ダウンロードCSVから自動で削除されます。")
        if rollup_options.enabled:
            rollup_summary = summarize_free_shipping_rollup(export_frame)
            sum_col1, sum_col2, sum_col3 = st.columns(3)
            sum_col1.metric("送料無料化する件数", rollup_summary["applied"])
            sum_col2.metric("スキップ件数", rollup_summary["skipped"])
            sum_col3.metric("平均転嫁送料", rollup_summary["average_transfer_usd"])
        st.download_button(
            "CSVをダウンロード",
            data=dataframe_to_csv_bytes(export_frame),
            file_name=output_name,
            mime="text/csv",
            use_container_width=True,
        )

    with workspace_col:
        st.markdown('<div class="section-title">商品確認</div>', unsafe_allow_html=True)
        workspace_view = st.radio(
            "商品確認表示",
            ["選択商品", "投入前チェック", "処理結果一覧", "処理診断", "除外候補", "CSV全体"],
            horizontal=True,
            label_visibility="collapsed",
            key=view_key,
        )
        if workspace_view == "選択商品":
            render_selected_preview(st, active_frame.iloc[selected_index], selected_index, title_col, price_col, image_col, url_col)
            render_free_shipping_rollup_preview(st, active_frame.iloc[selected_index], rollup_options)
        elif workspace_view == "投入前チェック":
            render_ebay_preflight_check(st, active_frame, export_frame, title_col)
        elif workspace_view == "処理結果一覧":
            render_clickable_review_table(st, active_frame, title_col, image_col, url_col)
        elif workspace_view == "処理診断":
            render_processing_diagnostics(st, active_frame, title_col, image_col, url_col)
        elif workspace_view == "除外候補":
            render_exclusion_candidates(st, active_frame, title_col, url_col, image_col, selected_index_key, view_key)
        else:
            st.dataframe(active_frame.head(300), use_container_width=True, height=REVIEW_TABLE_HEIGHT_PX)


def render_global_styles(st) -> None:
    st.markdown(
        """
        <style>
        :root {
            --app-text: #172033;
            --app-muted: #667085;
            --app-panel: #ffffff;
            --app-bg: #f7f8fb;
            --app-border: #dbe3ef;
            --app-control: #101828;
            --app-accent: #ef4444;
            --app-soft: #f1f5f9;
        }
        .stApp {
            background: var(--app-bg);
            color: var(--app-text);
        }
        .stApp, .stApp p, .stApp span, .stApp label, .stApp div {
            color: var(--app-text);
        }
        .block-container {
            max-width: 1540px;
            padding-top: 1.1rem;
            padding-bottom: 2rem;
        }
        h1, h2, h3, h4, h5, h6 {
            color: #0f1f3d !important;
            letter-spacing: 0;
        }
        .app-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-end;
            gap: 16px;
            margin-bottom: 14px;
            padding-bottom: 10px;
            border-bottom: 1px solid var(--app-border);
        }
        .app-header h1 {
            margin: 0;
            font-size: 34px;
            line-height: 1.18;
        }
        .app-kicker {
            color: var(--app-muted) !important;
            font-size: 13px;
            font-weight: 700;
            margin-bottom: 4px;
            text-transform: uppercase;
        }
        .header-badge {
            background: #111827;
            color: #ffffff !important;
            border-radius: 999px;
            padding: 8px 13px;
            font-size: 13px;
            font-weight: 700;
            white-space: nowrap;
        }
        .empty-state {
            background: #ffffff;
            border: 1px dashed #b6c2d4;
            border-radius: 8px;
            padding: 28px;
            margin-top: 14px;
        }
        .empty-state h3 {
            margin: 0 0 8px;
            font-size: 22px;
        }
        .empty-state p {
            margin: 0;
            color: var(--app-muted) !important;
        }
        .section-title {
            font-size: 15px;
            font-weight: 800;
            margin: 16px 0 8px;
            color: #0f1f3d !important;
        }
        .status-strip {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 10px;
            margin: 10px 0 16px;
        }
        .status-item {
            background: #ffffff;
            border: 1px solid var(--app-border);
            border-radius: 8px;
            padding: 11px 13px;
            min-height: 74px;
        }
        .status-label {
            color: var(--app-muted) !important;
            font-size: 12px;
            font-weight: 700;
            margin-bottom: 5px;
        }
        .status-value {
            font-size: 18px;
            font-weight: 800;
            color: var(--app-text) !important;
            overflow-wrap: anywhere;
        }
        .mapping-ok, .mapping-miss {
            display: inline-block;
            border-radius: 999px;
            padding: 4px 9px;
            font-size: 12px;
            font-weight: 700;
            margin: 2px 4px 2px 0;
        }
        .mapping-ok {
            background: #e8f7ef;
            color: #166534 !important;
        }
        .mapping-miss {
            background: #fff7ed;
            color: #9a3412 !important;
        }
        input,
        textarea,
        [data-baseweb="select"] > div,
        [data-testid="stNumberInput"] input {
            background: #ffffff !important;
            color: var(--app-text) !important;
            border-color: #cbd5e1 !important;
        }
        [data-baseweb="select"] span,
        [data-baseweb="select"] svg,
        [data-testid="stNumberInput"] button,
        [data-testid="stNumberInput"] button * {
            color: var(--app-text) !important;
            fill: var(--app-text) !important;
        }
        [data-testid="stFileUploaderDropzone"] {
            background: #ffffff !important;
            border: 1px solid var(--app-border) !important;
        }
        [data-testid="stFileUploaderDropzone"] * {
            color: var(--app-text) !important;
        }
        button[kind="primary"] {
            background: var(--app-accent) !important;
            border-color: var(--app-accent) !important;
            color: #ffffff !important;
        }
        button[kind="secondary"] {
            background: var(--app-control) !important;
            border-color: var(--app-control) !important;
            color: #ffffff !important;
        }
        button[kind="primary"] *,
        button[kind="secondary"] * {
            color: #ffffff !important;
        }
        div[data-testid="stMetric"] {
            background: #ffffff;
            border: 1px solid var(--app-border);
            border-radius: 8px;
            padding: 12px 14px;
            box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04);
        }
        div[data-testid="stMetric"] *,
        [data-testid="stMetricLabel"],
        [data-testid="stMetricValue"] {
            color: var(--app-text) !important;
        }
        .preview-metric-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 12px;
            margin: 10px 0 18px;
        }
        .preview-metric-card {
            background: #ffffff;
            border: 1px solid var(--app-border);
            border-radius: 8px;
            padding: 13px 14px;
            min-height: 104px;
            box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04);
        }
        .preview-metric-label {
            color: var(--app-muted) !important;
            font-size: 13px;
            font-weight: 800;
            margin-bottom: 8px;
            line-height: 1.25;
        }
        .preview-metric-value {
            color: #0f1f3d !important;
            font-size: clamp(20px, 2.1vw, 30px);
            font-weight: 850;
            line-height: 1.12;
            letter-spacing: 0;
            white-space: normal;
            overflow-wrap: anywhere;
            word-break: break-word;
        }
        .preview-metric-sub {
            color: var(--app-muted) !important;
            font-size: 12px;
            font-weight: 750;
            margin-top: 8px;
            line-height: 1.3;
            overflow-wrap: anywhere;
        }
        [data-testid="stDataFrame"] {
            border: 1px solid var(--app-border);
            border-radius: 8px;
            overflow: hidden;
            background: #ffffff;
        }
        [data-testid="stDataFrame"] * {
            color: var(--app-text);
        }
        .result-note {
            border: 1px solid var(--app-border);
            background: #ffffff;
            color: var(--app-text);
            border-radius: 8px;
            padding: 13px 15px;
            margin: 8px 0 12px;
            line-height: 1.65;
            overflow-wrap: anywhere;
        }
        .result-note * {
            color: var(--app-text) !important;
        }
        .result-note a {
            color: #1d4ed8 !important;
            font-weight: 700;
        }
        .specifics-summary {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 8px;
            margin: 8px 0 10px;
        }
        .specifics-count {
            background: #ffffff;
            border: 1px solid var(--app-border);
            border-radius: 8px;
            padding: 10px 12px;
        }
        .specifics-count strong {
            display: block;
            font-size: 20px;
            line-height: 1.1;
            color: #0f1f3d !important;
        }
        .specifics-count span {
            color: var(--app-muted) !important;
            font-size: 12px;
            font-weight: 700;
        }
        .specifics-mini-summary {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 8px;
            margin: 8px 0 10px;
        }
        .specifics-mini-summary div {
            border: 1px solid var(--app-border);
            background: #ffffff;
            border-radius: 8px;
            padding: 10px 12px;
        }
        .specifics-mini-summary strong {
            display: block;
            font-size: 20px;
            line-height: 1.1;
            color: #0f1f3d !important;
        }
        .specifics-mini-summary span {
            display: block;
            margin-top: 4px;
            color: var(--app-muted) !important;
            font-size: 12px;
            font-weight: 700;
        }
        .specifics-mini-table {
            width: 100%;
            border-collapse: collapse;
            border: 1px solid var(--app-border);
            border-radius: 8px;
            overflow: hidden;
            background: #ffffff;
            margin: 8px 0 12px;
            font-size: 13px;
        }
        .specifics-mini-table td {
            border-bottom: 1px solid #e8edf5;
            padding: 10px 12px;
            vertical-align: top;
            color: var(--app-text) !important;
        }
        .specifics-mini-table tr:last-child td {
            border-bottom: none;
        }
        .specifics-mini-table td:first-child {
            width: 38%;
            font-weight: 800;
        }
        .specifics-mini-table small {
            display: block;
            margin-top: 4px;
            color: var(--app-muted) !important;
            font-size: 12px;
            line-height: 1.35;
            font-weight: 600;
        }
        .specifics-table {
            width: 100%;
            border-collapse: collapse;
            background: #ffffff;
            border: 1px solid var(--app-border);
            border-radius: 8px;
            overflow: hidden;
            font-size: 13px;
        }
        .specifics-table th {
            background: #f8fafc;
            color: #344054 !important;
            text-align: left;
            padding: 8px 10px;
            border-bottom: 1px solid var(--app-border);
            font-weight: 800;
        }
        .specifics-table td {
            padding: 8px 10px;
            border-bottom: 1px solid #eef2f7;
            vertical-align: top;
        }
        .specifics-table tr:last-child td {
            border-bottom: 0;
        }
        .spec-badge {
            display: inline-block;
            border-radius: 999px;
            padding: 3px 8px;
            font-size: 12px;
            font-weight: 800;
            white-space: nowrap;
        }
        .spec-filled {
            background: #dcfce7;
            color: #166534 !important;
        }
        .spec-existing {
            background: #e0f2fe;
            color: #075985 !important;
        }
        .spec-missing {
            background: #fff7ed;
            color: #9a3412 !important;
        }
        .spec-pending {
            background: #f1f5f9;
            color: #475467 !important;
        }
        .image-shell img {
            border-radius: 8px;
            border: 1px solid var(--app-border);
            max-height: 520px;
            object-fit: contain;
        }
        .gallery-title {
            margin: 10px 0 6px;
            color: #0f1f3d !important;
            font-size: 13px;
            font-weight: 850;
        }
        .image-gallery {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 8px;
            margin-bottom: 10px;
        }
        .gallery-thumb {
            display: block;
            position: relative;
            overflow: hidden;
            border: 1px solid var(--app-border);
            border-radius: 8px;
            background: #ffffff;
            aspect-ratio: 1 / 1;
            text-decoration: none !important;
        }
        .gallery-thumb img {
            width: 100%;
            height: 100%;
            object-fit: cover;
            display: block;
        }
        .gallery-thumb span {
            position: absolute;
            left: 6px;
            bottom: 6px;
            border-radius: 999px;
            padding: 2px 7px;
            background: rgba(15, 31, 61, 0.78);
            color: #ffffff !important;
            font-size: 11px;
            font-weight: 800;
        }
        .compact-notice {
            border: 1px solid #bfdbfe;
            background: #eff6ff;
            color: #1e3a8a !important;
            border-radius: 8px;
            padding: 10px 12px;
            margin: 4px 0 10px;
            font-size: 13px;
            font-weight: 700;
            line-height: 1.45;
        }
        .clickable-list {
            border: 1px solid var(--app-border);
            border-radius: 8px;
            overflow: auto;
            background: #ffffff;
            max-height: 780px;
        }
        .clickable-row {
            display: grid;
            grid-template-columns: 54px 206px minmax(260px, 1fr) 84px 112px 112px 118px 140px;
            gap: 0;
            min-width: 1180px;
            border-bottom: 1px solid #e5e7eb;
            align-items: stretch;
        }
        .clickable-row.header {
            position: sticky;
            top: 0;
            z-index: 2;
            background: #f8fafc;
            color: #475467 !important;
            font-size: 12px;
            font-weight: 800;
            min-height: 42px;
        }
        .clickable-cell {
            padding: 10px 12px;
            border-right: 1px solid #e5e7eb;
            display: flex;
            align-items: center;
            min-width: 0;
            color: var(--app-text) !important;
            overflow-wrap: anywhere;
            line-height: 1.35;
        }
        .clickable-row:not(.header):hover {
            background: #eff6ff;
        }
        .clickable-image-link {
            display: block;
            width: 178px;
            height: 132px;
            border-radius: 7px;
            overflow: hidden;
            border: 2px solid transparent;
            background: #eef2f7;
            text-decoration: none !important;
        }
        .clickable-image-link:hover {
            border-color: #ef4444;
            box-shadow: 0 8px 18px rgba(15, 23, 42, 0.16);
        }
        .clickable-image-link img {
            width: 100%;
            height: 100%;
            object-fit: cover;
            display: block;
        }
        .clickable-image-placeholder {
            width: 100%;
            height: 100%;
            display: flex;
            align-items: center;
            justify-content: center;
            color: #667085 !important;
            font-size: 12px;
            font-weight: 800;
        }
        .diagnostic-row {
            display: grid;
            grid-template-columns: 54px 206px minmax(260px, 1fr) 116px 132px minmax(240px, 0.9fr) minmax(340px, 1.15fr);
            gap: 0;
            min-width: 1340px;
            border-bottom: 1px solid #e5e7eb;
            align-items: stretch;
        }
        .diagnostic-row.header {
            position: sticky;
            top: 0;
            z-index: 2;
            background: #f8fafc;
            color: #475467 !important;
            font-size: 12px;
            font-weight: 800;
            min-height: 42px;
        }
        .diagnostic-badge {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            border-radius: 999px;
            padding: 4px 9px;
            font-size: 12px;
            font-weight: 800;
            white-space: nowrap;
        }
        .diagnostic-ok {
            background: #dcfce7;
            color: #166534 !important;
        }
        .diagnostic-warning {
            background: #fff7ed;
            color: #9a3412 !important;
        }
        .diagnostic-excluded {
            background: #fee2e2;
            color: #991b1b !important;
        }
        .diagnostic-pending {
            background: #f1f5f9;
            color: #475467 !important;
        }
        .click-hint {
            color: var(--app-muted) !important;
            font-size: 12px;
            font-weight: 700;
            margin: 0 0 8px;
        }
        @media (max-width: 900px) {
            .app-header {
                align-items: flex-start;
                flex-direction: column;
            }
            .status-strip,
            .preview-metric-grid {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }
        }
        @media (max-width: 560px) {
            .preview-metric-grid {
                grid-template-columns: 1fr;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_file_summary(st, file_name: str, row_count: int, encoding: str, frame: pd.DataFrame) -> None:
    processed_count = sum(1 for _, row in frame.iterrows() if get_row_value(row, "Scrape Status") or get_row_value(row, "Detected Book Count"))
    shipping_count = sum(1 for _, row in frame.iterrows() if get_row_value(row, "FICP Shipping USD"))
    excluded_count = sum(1 for _, row in frame.iterrows() if get_row_value(row, "Listing Eligibility").lower() == "excluded")
    st.markdown(
        f"""
        <div class="status-strip">
          <div class="status-item">
            <div class="status-label">CSV</div>
            <div class="status-value">{html_escape(file_name)}</div>
          </div>
          <div class="status-item">
            <div class="status-label">行数</div>
            <div class="status-value">{row_count:,}</div>
          </div>
          <div class="status-item">
            <div class="status-label">処理済み</div>
            <div class="status-value">{processed_count:,}</div>
          </div>
          <div class="status-item">
            <div class="status-label">送料入力済み</div>
            <div class="status-value">{shipping_count:,} <span style="font-size:12px; color:#667085;">/ {html_escape(encoding)}</span></div>
          </div>
          <div class="status-item">
            <div class="status-label">出品除外</div>
            <div class="status-value">{excluded_count:,}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_mapping_status(
    st,
    url_col: str,
    image_col: str,
    title_col: str,
    description_col: str,
    shipping_profile_col: str,
    shipping_col: str,
) -> None:
    items = [
        ("参照元URL/画像URL", url_col),
        ("画像URL", image_col),
        ("タイトル", title_col),
        ("Description", description_col),
        ("配送ポリシー", shipping_profile_col),
        ("送料額列", shipping_col or "通常未使用"),
    ]
    chips = []
    for label, value in items:
        css_class = "mapping-ok" if value else "mapping-miss"
        display = value or "未選択"
        chips.append(f'<span class="{css_class}">{html_escape(label)}: {html_escape(display)}</span>')
    st.markdown("".join(chips), unsafe_allow_html=True)


def format_row_label(row: pd.Series, idx: int, title_col: str) -> str:
    title = get_row_value(row, title_col) if title_col else ""
    if not title:
        title = get_row_value(row, "C:Book Title") or get_row_value(row, "Detected Book Count") or "untitled"
    eligibility = get_row_value(row, "Listing Eligibility")
    count = get_row_value(row, "Detected Book Count")
    shipping = get_row_value(row, "FICP Shipping USD")
    suffix = []
    if eligibility.lower() == "excluded":
        suffix.append("出品除外")
    if count:
        suffix.append(f"{count}冊")
    if shipping:
        suffix.append(f"${shipping}")
    tail = f" / {' / '.join(suffix)}" if suffix else ""
    return f"{idx + 1}: {title[:72]}{tail}"


def display_source_url(row: pd.Series, url_col: str) -> str:
    mapped_url = get_row_value(row, url_col)
    inferred_url = get_row_value(row, "Inferred Source URL")
    if mapped_url and not is_likely_image_url(mapped_url):
        return mapped_url
    return first_nonblank(inferred_url, mapped_url)


def apply_query_selected_row(st, row_options: list[int], selected_index_key: str, view_key: str) -> None:
    try:
        raw_value = st.query_params.get("comic_ficp_select")
    except Exception:
        return
    if raw_value is None:
        return
    if isinstance(raw_value, list):
        raw_value = raw_value[0] if raw_value else ""
    try:
        selected_position = int(str(raw_value))
    except ValueError:
        selected_position = -1
    if selected_position in row_options:
        st.session_state[selected_index_key] = selected_position
        st.session_state[view_key] = "選択商品"
    try:
        del st.query_params["comic_ficp_select"]
    except Exception:
        pass


def build_select_product_href(position: int) -> str:
    return f"?comic_ficp_select={int(position)}"


def render_clickable_review_table(st, frame: pd.DataFrame, title_col: str, image_col: str, url_col: str) -> None:
    st.markdown('<div class="click-hint">画像をクリックすると、その商品を「選択商品」で開きます。</div>', unsafe_allow_html=True)
    rows_html = [
        '<div class="clickable-row header">'
        '<div class="clickable-cell">No</div>'
        '<div class="clickable-cell">画像</div>'
        '<div class="clickable-cell">Title</div>'
        '<div class="clickable-cell">Books</div>'
        '<div class="clickable-cell">課金重量</div>'
        '<div class="clickable-cell">送料USD</div>'
        '<div class="clickable-cell">出品判定</div>'
        '<div class="clickable-cell">取得状態</div>'
        "</div>"
    ]
    for position, (_, row) in enumerate(frame.iterrows()):
        rows_html.append(build_clickable_review_row_html(position, row, title_col, image_col, url_col))
    st.markdown(f'<div class="clickable-list">{"".join(rows_html)}</div>', unsafe_allow_html=True)


def build_clickable_review_row_html(position: int, row: pd.Series, title_col: str, image_col: str, url_col: str) -> str:
    image_url = build_table_image_url(row, image_col)
    href = build_select_product_href(position)
    if image_url:
        image_html = (
            f'<a class="clickable-image-link" href="{html_escape(href)}" target="_self" title="この商品を選択商品で開く">'
            f'<img src="{html_escape(image_url)}" alt="{html_escape(get_row_value(row, title_col) or "商品画像")}">'
            "</a>"
        )
    else:
        image_html = (
            f'<a class="clickable-image-link" href="{html_escape(href)}" target="_self" title="この商品を選択商品で開く">'
            '<div class="clickable-image-placeholder">画像なし</div>'
            "</a>"
        )
    title = first_nonblank(get_row_value(row, title_col), get_row_value(row, "C:Book Title"), get_row_value(row, "Source Listing Title"))
    billable_weight = format_weight_display(get_row_value(row, "Billable Weight kg"))
    shipping_usd = get_row_value(row, "FICP Shipping USD")
    shipping_text = f"${shipping_usd}" if shipping_usd else "-"
    eligibility = get_row_value(row, "Listing Eligibility") or "-"
    status_parts = [get_row_value(row, "Scrape Status")]
    book_count_status = get_row_value(row, "Book Count Status")
    if book_count_status and book_count_status.lower() != "ok":
        status_parts.append(book_count_status)
    status = " / ".join(part for part in status_parts if part) or "-"
    return (
        '<div class="clickable-row">'
        f'<div class="clickable-cell">{position + 1}</div>'
        f'<div class="clickable-cell">{image_html}</div>'
        f'<div class="clickable-cell"><a href="{html_escape(href)}" target="_self">{html_escape(title or "-")}</a></div>'
        f'<div class="clickable-cell">{html_escape(get_row_value(row, "Detected Book Count") or "-")}</div>'
        f'<div class="clickable-cell">{html_escape(billable_weight)}</div>'
        f'<div class="clickable-cell">{html_escape(shipping_text)}</div>'
        f'<div class="clickable-cell">{html_escape(eligibility)}</div>'
        f'<div class="clickable-cell">{html_escape(status)}</div>'
        "</div>"
    )


def build_processing_diagnostic_table(frame: pd.DataFrame, title_col: str, url_col: str, image_col: str = "") -> pd.DataFrame:
    rows: list[dict[str, str]] = []
    for idx, row in frame.iterrows():
        diagnostics = diagnose_processed_row(row)
        result = get_row_value(row, "Processing Result") or diagnostics["result"]
        severity = get_row_value(row, "Processing Severity") or diagnostics["severity"]
        needs_review = get_row_value(row, "Needs Review") or diagnostics["needs_review"]
        review_reason = redact_sensitive_text(get_row_value(row, "Needs Review Reason") or diagnostics["review_reason"])
        diagnostic_text = redact_sensitive_text(get_row_value(row, "Processing Diagnostics") or diagnostics["diagnostics"])
        rows.append(
            {
                "No": str(idx + 1),
                "Image": build_table_image_url(row, image_col),
                "Title": first_nonblank(
                    get_row_value(row, title_col),
                    get_row_value(row, "Source Listing Title"),
                    get_row_value(row, "C:Book Title"),
                ),
                "Result": result,
                "Severity": severity,
                "Needs Review": needs_review,
                "Review Reason": review_reason,
                "Diagnostics": diagnostic_text,
                "Source Status": get_row_value(row, "Scrape Status"),
                "Books": get_row_value(row, "Detected Book Count"),
                "Book Count Status": get_row_value(row, "Book Count Status"),
                "Reference Count": get_row_value(row, "Reference Book Count"),
                "Reference Status": get_row_value(row, "Reference Count Status"),
                "Reference Evidence": get_row_value(row, "Reference Count Evidence"),
                "Billable kg": get_row_value(row, "Billable Weight kg"),
                "Shipping USD": get_row_value(row, "FICP Shipping USD"),
                "Eligibility": get_row_value(row, "Listing Eligibility"),
                "AI": get_row_value(row, "AI Enrichment Status"),
                "URL": display_source_url(row, url_col),
            }
        )
    return pd.DataFrame(rows)


def diagnostic_badge_class(result: str) -> str:
    lowered = (result or "").lower()
    if "成功" in result or lowered == "ok":
        return "diagnostic-ok"
    if "除外" in result or "excluded" in lowered:
        return "diagnostic-excluded"
    if "未処理" in result:
        return "diagnostic-pending"
    return "diagnostic-warning"


def diagnostic_matches_filter(diagnostics: dict[str, str], filter_label: str) -> bool:
    result = diagnostics["result"]
    needs_review = diagnostics["needs_review"].lower() == "yes"
    if filter_label == "確認が必要":
        return result == "確認必要" or (needs_review and result != "出品除外")
    if filter_label == "出品除外":
        return result == "出品除外"
    if filter_label == "未処理":
        return result == "未処理"
    if filter_label == "成功のみ":
        return result == "成功"
    return True


def render_processing_diagnostics(st, frame: pd.DataFrame, title_col: str, image_col: str, url_col: str) -> None:
    table = build_processing_diagnostic_table(frame, title_col, url_col, image_col)
    if table.empty:
        st.info("診断できるデータがまだありません。CSVを読み込むとここに処理状況が表示されます。")
        return

    total_count = len(table)
    success_count = int((table["Result"] == "成功").sum())
    review_count = int((table["Result"] == "確認必要").sum())
    excluded_count = int((table["Result"] == "出品除外").sum())
    pending_count = int((table["Result"] == "未処理").sum())
    st.markdown(
        f"""
        <div class="status-strip">
          <div class="status-item"><div class="status-label">全体</div><div class="status-value">{total_count:,}</div></div>
          <div class="status-item"><div class="status-label">成功</div><div class="status-value">{success_count:,}</div></div>
          <div class="status-item"><div class="status-label">確認必要</div><div class="status-value">{review_count:,}</div></div>
          <div class="status-item"><div class="status-label">出品除外</div><div class="status-value">{excluded_count:,}</div></div>
          <div class="status-item"><div class="status-label">未処理</div><div class="status-value">{pending_count:,}</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    filter_label = st.radio(
        "診断表示",
        ["すべて", "確認が必要", "出品除外", "未処理", "成功のみ"],
        horizontal=True,
        label_visibility="collapsed",
        key="comic_ficp_diagnostic_filter",
    )
    render_clickable_diagnostic_table(st, frame, title_col, image_col, url_col, filter_label)


def render_ebay_preflight_check(st, active_frame: pd.DataFrame, export_frame: pd.DataFrame, title_col: str) -> None:
    table = build_ebay_preflight_table(active_frame, export_frame, title_col)
    if table.empty:
        st.info("ダウンロード対象のデータがありません。出品除外行だけの場合は除外候補を確認してください。")
        return

    target_rows = table[table["Status"] != "除外済み"]
    ok_count = int((target_rows["Status"] == "OK").sum())
    warning_count = int((target_rows["Status"] == "注意").sum())
    error_count = int((target_rows["Status"] == "要修正").sum())
    excluded_count = int((table["Status"] == "除外済み").sum())
    multi_image_count = int(pd.to_numeric(target_rows["Images"], errors="coerce").fillna(0).gt(1).sum())
    st.markdown(
        f"""
        <div class="status-strip">
          <div class="status-item"><div class="status-label">出力対象</div><div class="status-value">{len(target_rows):,}</div></div>
          <div class="status-item"><div class="status-label">OK</div><div class="status-value">{ok_count:,}</div></div>
          <div class="status-item"><div class="status-label">注意</div><div class="status-value">{warning_count:,}</div></div>
          <div class="status-item"><div class="status-label">要修正</div><div class="status-value">{error_count:,}</div></div>
          <div class="status-item"><div class="status-label">複数画像</div><div class="status-value">{multi_image_count:,}</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if excluded_count:
        st.caption("出品除外行はダウンロードCSVから外れます。理由は除外候補タブで確認できます。")
    if error_count:
        st.error("eBay投入前に修正した方がよい行があります。Issues列を確認してください。")
    elif warning_count:
        st.warning("致命的ではありませんが、確認した方がよい行があります。Warnings列を確認してください。")
    else:
        st.success("ダウンロード対象に大きな問題は見つかりませんでした。")

    st.dataframe(
        table,
        use_container_width=True,
        height=REVIEW_TABLE_HEIGHT_PX,
        column_config={
            "Image": st.column_config.ImageColumn("画像", width="small"),
            "Status": st.column_config.TextColumn("判定", width="small"),
            "Title": st.column_config.TextColumn("Title", width="large"),
            "Images": st.column_config.TextColumn("画像数", width="small"),
            "Issues": st.column_config.TextColumn("要修正", width="large"),
            "Warnings": st.column_config.TextColumn("注意", width="large"),
        },
    )


def render_clickable_diagnostic_table(
    st,
    frame: pd.DataFrame,
    title_col: str,
    image_col: str,
    url_col: str,
    filter_label: str,
) -> None:
    st.markdown(
        '<div class="click-hint">画像やタイトルをクリックすると、その商品を「選択商品」で開きます。確認必要の理由を優先して表示します。</div>',
        unsafe_allow_html=True,
    )
    rows_html = [
        '<div class="diagnostic-row header">'
        '<div class="clickable-cell">No</div>'
        '<div class="clickable-cell">画像</div>'
        '<div class="clickable-cell">Title</div>'
        '<div class="clickable-cell">結果</div>'
        '<div class="clickable-cell">送料/冊数</div>'
        '<div class="clickable-cell">要確認理由</div>'
        '<div class="clickable-cell">診断メモ</div>'
        "</div>"
    ]
    visible_count = 0
    for position, (_, row) in enumerate(frame.iterrows()):
        diagnostics = diagnose_processed_row(row)
        diagnostics["result"] = get_row_value(row, "Processing Result") or diagnostics["result"]
        diagnostics["severity"] = get_row_value(row, "Processing Severity") or diagnostics["severity"]
        diagnostics["needs_review"] = get_row_value(row, "Needs Review") or diagnostics["needs_review"]
        diagnostics["review_reason"] = redact_sensitive_text(get_row_value(row, "Needs Review Reason") or diagnostics["review_reason"])
        diagnostics["diagnostics"] = redact_sensitive_text(get_row_value(row, "Processing Diagnostics") or diagnostics["diagnostics"])
        if not diagnostic_matches_filter(diagnostics, filter_label):
            continue
        rows_html.append(build_clickable_diagnostic_row_html(position, row, title_col, image_col, diagnostics))
        visible_count += 1
    if visible_count == 0:
        st.info("この条件に当てはまる行はありません。")
        return
    st.markdown(f'<div class="clickable-list">{"".join(rows_html)}</div>', unsafe_allow_html=True)


def build_clickable_diagnostic_row_html(
    position: int,
    row: pd.Series,
    title_col: str,
    image_col: str,
    diagnostics: dict[str, str],
) -> str:
    image_url = build_table_image_url(row, image_col)
    href = build_select_product_href(position)
    title = first_nonblank(get_row_value(row, title_col), get_row_value(row, "Source Listing Title"), get_row_value(row, "C:Book Title"))
    if image_url:
        image_html = (
            f'<a class="clickable-image-link" href="{html_escape(href)}" target="_self" title="この商品を選択商品で開く">'
            f'<img src="{html_escape(image_url)}" alt="{html_escape(title or "商品画像")}">'
            "</a>"
        )
    else:
        image_html = (
            f'<a class="clickable-image-link" href="{html_escape(href)}" target="_self" title="この商品を選択商品で開く">'
            '<div class="clickable-image-placeholder">画像なし</div>'
            "</a>"
        )
    shipping = get_row_value(row, "FICP Shipping USD")
    books = get_row_value(row, "Detected Book Count")
    shipping_books = f"${shipping or '-'} / {books or '-'}冊"
    result = diagnostics["result"]
    badge_class = diagnostic_badge_class(result)
    review_reason = diagnostics["review_reason"] or "-"
    diagnostic_text = diagnostics["diagnostics"] or "-"
    return (
        '<div class="diagnostic-row">'
        f'<div class="clickable-cell">{position + 1}</div>'
        f'<div class="clickable-cell">{image_html}</div>'
        f'<div class="clickable-cell"><a href="{html_escape(href)}" target="_self">{html_escape(title or "-")}</a></div>'
        f'<div class="clickable-cell"><span class="diagnostic-badge {badge_class}">{html_escape(result)}</span></div>'
        f'<div class="clickable-cell">{html_escape(shipping_books)}</div>'
        f'<div class="clickable-cell">{html_escape(review_reason)}</div>'
        f'<div class="clickable-cell">{html_escape(diagnostic_text)}</div>'
        "</div>"
    )


def build_review_table(frame: pd.DataFrame, title_col: str, url_col: str, image_col: str = "") -> pd.DataFrame:
    rows: list[dict[str, str]] = []
    for idx, row in frame.iterrows():
        source_url = display_source_url(row, url_col)
        rows.append(
            {
                "No": str(idx + 1),
                "Image": build_table_image_url(row, image_col),
                "Title": first_nonblank(get_row_value(row, title_col), get_row_value(row, "C:Book Title")),
                "Books": get_row_value(row, "Detected Book Count"),
                "Book Count Status": get_row_value(row, "Book Count Status"),
                "Reference Count": get_row_value(row, "Reference Book Count"),
                "Reference Status": get_row_value(row, "Reference Count Status"),
                "Reference Evidence": get_row_value(row, "Reference Count Evidence"),
                "Actual kg": first_nonblank(get_row_value(row, "Estimated Actual Weight kg"), get_row_value(row, "Estimated Weight kg")),
                "Packaging kg": get_row_value(row, "Estimated Packaging Weight kg"),
                "Packaging Materials": get_row_value(row, "Packaging Materials"),
                "Dim kg": get_row_value(row, "Dimensional Weight kg"),
                "Billable kg": get_row_value(row, "Billable Weight kg"),
                "Billable Source": get_row_value(row, "Billable Weight Source"),
                "Base JPY": get_row_value(row, "FICP Base Shipping JPY"),
                "Fuel %": get_row_value(row, "FICP Fuel Surcharge Percent"),
                "Fuel JPY": get_row_value(row, "FICP Fuel Surcharge JPY"),
                "Shipping JPY": get_row_value(row, "FICP Shipping JPY"),
                "Shipping USD": get_row_value(row, "FICP Shipping USD"),
                "Eligibility": get_row_value(row, "Listing Eligibility"),
                "Exclusion Reason": get_row_value(row, "Exclusion Reason"),
                "Exclusion Evidence": get_row_value(row, "Exclusion Evidence"),
                "Source Title": get_row_value(row, "Source Listing Title"),
                "Source Price": get_row_value(row, "Source Listing Price"),
                "Source": get_row_value(row, "Source URL Confidence"),
                "Status": get_row_value(row, "Scrape Status"),
                "AI": get_row_value(row, "AI Enrichment Status"),
                "Description Notes": get_row_value(row, "Description Detail Notes"),
                "URL": source_url,
            }
        )
    return pd.DataFrame(rows)


def build_exclusion_table(frame: pd.DataFrame, title_col: str, url_col: str, image_col: str = "") -> pd.DataFrame:
    rows: list[dict[str, str]] = []
    for idx, row in frame.iterrows():
        if get_row_value(row, "Listing Eligibility").lower() != "excluded":
            continue
        rows.append(
            {
                "No": str(idx + 1),
                "Image": build_table_image_url(row, image_col),
                "Title": first_nonblank(
                    get_row_value(row, title_col),
                    get_row_value(row, "Source Listing Title"),
                    get_row_value(row, "C:Book Title"),
                ),
                "Reason": get_row_value(row, "Exclusion Reason"),
                "Evidence": get_row_value(row, "Exclusion Evidence"),
                "Source Description": get_row_value(row, "Source Listing Description"),
                "Status": get_row_value(row, "Scrape Status"),
                "URL": display_source_url(row, url_col),
            }
        )
    return pd.DataFrame(rows)


def render_exclusion_candidates(
    st,
    frame: pd.DataFrame,
    title_col: str,
    url_col: str,
    image_col: str = "",
    selected_index_key: str = "comic_ficp_selected_index",
    view_key: str = "comic_ficp_workspace_view",
) -> None:
    table = build_exclusion_table(frame, title_col, url_col, image_col)
    if table.empty:
        st.info("除外候補はまだありません。欠巻・欠品・欠損の可能性がある商品を検出すると、ここに表示します。")
        return
    st.warning(f"除外候補 {len(table)} 件があります。これらはダウンロードCSVから自動で削除されます。")
    render_clickable_exclusion_table(st, frame, title_col, image_col)


def render_clickable_exclusion_table(st, frame: pd.DataFrame, title_col: str, image_col: str) -> None:
    st.markdown('<div class="click-hint">画像をクリックすると、その除外候補を「選択商品」で開きます。</div>', unsafe_allow_html=True)
    rows_html = [
        '<div class="clickable-row header">'
        '<div class="clickable-cell">No</div>'
        '<div class="clickable-cell">画像</div>'
        '<div class="clickable-cell">Title</div>'
        '<div class="clickable-cell">理由</div>'
        '<div class="clickable-cell" style="grid-column: span 3;">根拠</div>'
        '<div class="clickable-cell">取得状態</div>'
        "</div>"
    ]
    for position, (_, row) in enumerate(frame.iterrows()):
        if get_row_value(row, "Listing Eligibility").lower() != "excluded":
            continue
        rows_html.append(build_clickable_exclusion_row_html(position, row, title_col, image_col))
    st.markdown(f'<div class="clickable-list">{"".join(rows_html)}</div>', unsafe_allow_html=True)


def build_clickable_exclusion_row_html(position: int, row: pd.Series, title_col: str, image_col: str) -> str:
    image_url = build_table_image_url(row, image_col)
    href = build_select_product_href(position)
    if image_url:
        image_html = (
            f'<a class="clickable-image-link" href="{html_escape(href)}" target="_self" title="この除外候補を選択商品で開く">'
            f'<img src="{html_escape(image_url)}" alt="{html_escape(get_row_value(row, title_col) or "商品画像")}">'
            "</a>"
        )
    else:
        image_html = (
            f'<a class="clickable-image-link" href="{html_escape(href)}" target="_self" title="この除外候補を選択商品で開く">'
            '<div class="clickable-image-placeholder">画像なし</div>'
            "</a>"
        )
    title = first_nonblank(get_row_value(row, title_col), get_row_value(row, "Source Listing Title"), get_row_value(row, "C:Book Title"))
    return (
        '<div class="clickable-row">'
        f'<div class="clickable-cell">{position + 1}</div>'
        f'<div class="clickable-cell">{image_html}</div>'
        f'<div class="clickable-cell"><a href="{html_escape(href)}" target="_self">{html_escape(title or "-")}</a></div>'
        f'<div class="clickable-cell">{html_escape(get_row_value(row, "Exclusion Reason") or "-")}</div>'
        f'<div class="clickable-cell" style="grid-column: span 3;">{html_escape(get_row_value(row, "Exclusion Evidence") or "-")}</div>'
        f'<div class="clickable-cell">{html_escape(get_row_value(row, "Scrape Status") or "-")}</div>'
        "</div>"
    )


def build_specifics_review_rows(row: pd.Series, processed: bool) -> list[dict[str, str]]:
    filled = parse_specifics_field_map(get_row_value(row, "Specifics Filled Fields"))
    existing = parse_specifics_field_map(get_row_value(row, "Specifics Existing Fields"))
    not_filled = parse_specifics_field_map(get_row_value(row, "Specifics Not Filled Fields"))
    notes_text = get_row_value(row, "Specifics Fill Notes")
    rows: list[dict[str, str]] = []
    for column in get_specific_columns(row.index, include_defaults=True):
        value = get_row_value(row, column)
        if column in filled:
            status = "補完"
            note_reason = find_specifics_note_reason(notes_text, column)
            reason = f"今回の処理でNA/空欄へ入力: {note_reason}" if note_reason else "今回の処理でNA/空欄へ入力"
        elif column in existing:
            status = "既存値"
            reason = "CSV内の既存値を保持"
        elif column in not_filled or processed:
            status = "未補完"
            reason = "根拠が弱いため空欄のまま"
        else:
            status = "未処理"
            reason = "まだ処理していません"
        rows.append(
            {
                "column": column,
                "label": specific_label(column),
                "status": status,
                "value": value or "-",
                "reason": reason,
            }
        )
    return rows


IMPORTANT_SPECIFIC_COLUMNS = [
    "C:Grade",
    "C:Artist/Writer",
    "C:Author",
    "C:Genre",
    "C:Publisher",
    "C:Book Title",
    "C:Series",
    "C:Language",
    "C:Format",
    "C:Type",
]


def build_specifics_summary_items(row: pd.Series, processed: bool, limit: int = 8) -> list[dict[str, str]]:
    if not processed:
        return []
    review_rows = build_specifics_review_rows(row, processed)
    by_column = {item["column"]: item for item in review_rows}
    items: list[dict[str, str]] = []
    seen: set[str] = set()

    def add_item(column: str) -> None:
        if column in seen:
            return
        item = by_column.get(column)
        if not item or item["status"] != "補完":
            return
        value = str(item.get("value", "")).strip()
        if not value or value == "-":
            return
        items.append(
            {
                "label": item.get("label", specific_label(column)),
                "column": column,
                "value": value,
                "reason": item.get("reason", ""),
            }
        )
        seen.add(column)

    for column in IMPORTANT_SPECIFIC_COLUMNS:
        add_item(column)
    for item in review_rows:
        add_item(item["column"])
        if len(items) >= limit:
            break
    return items[:limit]


def render_specifics_compact_summary(st, row: pd.Series, processed: bool) -> None:
    rows = build_specifics_review_rows(row, processed)
    counts = {
        "filled": sum(1 for item in rows if item["status"] == "補完"),
        "existing": sum(1 for item in rows if item["status"] == "既存値"),
        "missing": sum(1 for item in rows if item["status"] == "未補完"),
    }
    st.markdown(
        f"""
        <div class="specifics-mini-summary">
          <div><strong>{counts["filled"]}</strong><span>今回補完</span></div>
          <div><strong>{counts["existing"]}</strong><span>既存値保持</span></div>
          <div><strong>{counts["missing"]}</strong><span>未補完</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    items = build_specifics_summary_items(row, processed)
    if not items:
        message = "補完された重要項目はまだありません。" if processed else "まだ処理されていません。"
        st.markdown(f'<div class="result-note">{html_escape(message)}</div>', unsafe_allow_html=True)
        return
    lines = []
    for item in items:
        reason = item.get("reason", "")
        reason_html = f"<small>{html_escape(reason)}</small>" if reason else ""
        lines.append(
            "<tr>"
            f"<td>{html_escape(item['label'])}<br><small>{html_escape(item['column'])}</small></td>"
            f"<td>{html_escape(item['value'])}{reason_html}</td>"
            "</tr>"
        )
    st.markdown(
        """
        <table class="specifics-mini-table">
          <tbody>
        """
        + "\n".join(lines)
        + """
          </tbody>
        </table>
        """,
        unsafe_allow_html=True,
    )
    raw_notes = get_row_value(row, "Specifics Fill Notes")
    if raw_notes:
        with st.expander("詳細ログを開く"):
            st.text(raw_notes)


def render_specifics_review(st, row: pd.Series, processed: bool) -> None:
    rows = build_specifics_review_rows(row, processed)
    counts = {
        "補完": sum(1 for item in rows if item["status"] == "補完"),
        "既存値": sum(1 for item in rows if item["status"] == "既存値"),
        "未補完": sum(1 for item in rows if item["status"] == "未補完"),
    }
    st.markdown(
        f"""
        <div class="specifics-summary">
          <div class="specifics-count"><strong>{len(rows)}</strong><span>Specifics項目</span></div>
          <div class="specifics-count"><strong>{counts["補完"]}</strong><span>今回補完</span></div>
          <div class="specifics-count"><strong>{counts["既存値"]}</strong><span>既存値保持</span></div>
          <div class="specifics-count"><strong>{counts["未補完"]}</strong><span>未補完</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    body_rows = []
    for item in rows:
        badge_class = {
            "補完": "spec-filled",
            "既存値": "spec-existing",
            "未補完": "spec-missing",
            "未処理": "spec-pending",
        }.get(item["status"], "spec-pending")
        body_rows.append(
            "<tr>"
            f"<td>{html_escape(item['label'])}<br><small>{html_escape(item['column'])}</small></td>"
            f"<td><span class=\"spec-badge {badge_class}\">{html_escape(item['status'])}</span></td>"
            f"<td>{html_escape(item['value'])}</td>"
            f"<td>{html_escape(item['reason'])}</td>"
            "</tr>"
        )
    st.markdown(
        """
        <table class="specifics-table">
          <thead>
            <tr><th>項目</th><th>状態</th><th>現在の値</th><th>判断</th></tr>
          </thead>
          <tbody>
        """
        + "\n".join(body_rows)
        + """
          </tbody>
        </table>
        """,
        unsafe_allow_html=True,
    )


def render_source_listing_info(st, row: pd.Series, processed: bool) -> None:
    source_title = get_row_value(row, "Source Listing Title")
    source_price = get_row_value(row, "Source Listing Price")
    source_description = get_row_value(row, "Source Listing Description")
    source_detail_preview = get_row_value(row, "Source Listing Detail Preview")
    status = get_row_value(row, "Scrape Status")

    if not any([source_title, source_price, source_description, source_detail_preview]):
        message = (
            "公開ページから商品情報は取得できませんでした。CSV内の情報で処理しています。"
            if processed
            else "まだ公開ページを取得していません。"
        )
        st.markdown(f'<div class="result-note">{html_escape(message)}</div>', unsafe_allow_html=True)
        return

    st.markdown(
        f"""
        <div class="result-note">
          <strong>取得タイトル:</strong> {html_escape(source_title or "-")}<br>
          <strong>取得価格:</strong> {html_escape(source_price or "-")}<br>
          <strong>取得状態:</strong> {html_escape(status or "-")}
        </div>
        """,
        unsafe_allow_html=True,
    )
    info_rows = []
    if source_description:
        info_rows.append(("商品説明", source_description))
    if source_detail_preview and source_detail_preview != source_description:
        info_rows.append(("ページ本文抜粋", source_detail_preview))
    if not info_rows:
        info_rows.append(("商品情報", "タイトルや画像は取得できましたが、出品者の商品説明・状態説明は取得できていません。"))

    table_rows = "\n".join(
        f"<tr><td>{html_escape(label)}</td><td>{html_escape(value)}</td></tr>"
        for label, value in info_rows
    )
    st.markdown(
        """
        <table class="specifics-table">
          <thead><tr><th>種類</th><th>取得内容</th></tr></thead>
          <tbody>
        """
        + table_rows
        + """
          </tbody>
        </table>
        """,
        unsafe_allow_html=True,
    )


def parse_float_text(value: object) -> Optional[float]:
    text = str(value or "").strip()
    if not text:
        return None
    text = re.sub(r"[^\d.\-]", "", text)
    if text in {"", ".", "-", "-."}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def format_weight_display(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return "-"
    if re.search(r"\bkg\b", text, flags=re.I):
        return text
    number = parse_float_text(text)
    return f"{number:.3f} kg" if number is not None else f"{text} kg"


def format_jpy_display(value: object) -> str:
    number = parse_float_text(value)
    if number is None:
        return ""
    return f"JPY {int(round(number)):,}円"


def build_preview_metric_items(
    price: object,
    book_count: object,
    weight_kg: object,
    shipping_jpy: object,
    shipping_usd: object,
) -> list[dict[str, str]]:
    shipping_usd_text = str(shipping_usd or "").strip()
    shipping_jpy_text = format_jpy_display(shipping_jpy)
    return [
        {"label": "価格", "value": str(price or "-").strip() or "-", "sub": ""},
        {"label": "冊数", "value": f"{book_count}冊" if str(book_count or "").strip() else "-", "sub": ""},
        {"label": "課金重量", "value": format_weight_display(weight_kg), "sub": ""},
        {
            "label": "送料USD",
            "value": f"${shipping_usd_text}" if shipping_usd_text else "-",
            "sub": shipping_jpy_text,
        },
    ]


def render_preview_metric_cards(st, metrics: list[dict[str, str]]) -> None:
    cards = []
    for item in metrics:
        sub = item.get("sub", "")
        sub_html = f'<div class="preview-metric-sub">{html_escape(sub)}</div>' if sub else ""
        cards.append(
            '<div class="preview-metric-card">'
            f'<div class="preview-metric-label">{html_escape(item.get("label", ""))}</div>'
            f'<div class="preview-metric-value">{html_escape(item.get("value", "-"))}</div>'
            f"{sub_html}"
            "</div>"
        )
    st.markdown(f'<div class="preview-metric-grid">{"".join(cards)}</div>', unsafe_allow_html=True)


def render_free_shipping_rollup_preview(st, row: pd.Series, options: FreeShippingRollupOptions) -> None:
    if not options.enabled:
        return
    original_price = get_row_value(row, options.price_col)
    base_shipping_usd = get_row_value(row, "FICP Base Shipping USD")
    fuel_surcharge_usd = get_row_value(row, "FICP Fuel Surcharge USD")
    total_shipping_usd = get_row_value(row, "FICP Shipping USD")
    calculation, status = calculate_free_shipping_rollup(
        start_price=original_price,
        shipping_usd=total_shipping_usd,
        markup_percent=options.markup_percent,
    )
    if calculation:
        markup_usd = f"${calculation['markup_usd']:.2f}"
        transfer_usd = f"${calculation['transfer_usd']:.2f}"
        adjusted_price = f"${calculation['adjusted_price']:.2f}"
    else:
        markup_usd = "-"
        transfer_usd = "-"
        adjusted_price = "-"
    policy_name = options.free_shipping_profile_name.strip() or DEFAULT_FREE_SHIPPING_PROFILE_NAME
    st.markdown('<div class="section-title">送料無料価格転嫁プレビュー</div>', unsafe_allow_html=True)
    st.markdown(
        f"""
        <div class="result-note">
        <strong>元価格:</strong> {html_escape(original_price or "-")}<br>
        <strong>FICP基本送料:</strong> {html_escape("$" + base_shipping_usd if base_shipping_usd else "-")}<br>
        <strong>燃油サーチャージ:</strong> {html_escape("$" + fuel_surcharge_usd if fuel_surcharge_usd else "-")}<br>
        <strong>FICP送料合計:</strong> {html_escape("$" + total_shipping_usd if total_shipping_usd else "-")}<br>
        <strong>{html_escape(f"{options.markup_percent:.1f}%")} 上乗せ額:</strong> {html_escape(markup_usd)}<br>
        <strong>価格へ転嫁する送料:</strong> {html_escape(transfer_usd)}<br>
        <strong>転嫁後StartPrice:</strong> {html_escape(adjusted_price)}<br>
        <strong>適用するShippingProfileName:</strong> {html_escape(policy_name)}<br>
        <strong>判定:</strong> {html_escape(status)}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_additional_image_gallery(st, image_urls: list[str]) -> None:
    if not image_urls:
        return
    items = []
    for index, url in enumerate(image_urls[:6], start=2):
        safe_url = html_escape(url)
        items.append(
            '<a class="gallery-thumb" href="{url}" target="_blank" title="画像{index}を開く">'
            '<img src="{url}" alt="商品画像 {index}">'
            '<span>画像 {index}</span>'
            "</a>".format(url=safe_url, index=index)
        )
    st.markdown(
        '<div class="gallery-title">追加画像</div>'
        f'<div class="image-gallery">{"".join(items)}</div>',
        unsafe_allow_html=True,
    )


def render_selected_preview(
    st,
    row: pd.Series,
    selected_index: int,
    title_col: str,
    price_col: str,
    image_col: str,
    url_col: str,
) -> None:
    title = first_nonblank(get_row_value(row, title_col), f"Row {selected_index + 1}")
    price = get_row_value(row, price_col)
    preview_image_urls = build_preview_image_urls(row, image_col)
    image_url = first_nonblank(*preview_image_urls)
    additional_image_urls = preview_image_urls[1:]
    book_count = get_row_value(row, "Detected Book Count")
    book_count_status = get_row_value(row, "Book Count Status")
    actual_weight_kg = first_nonblank(get_row_value(row, "Estimated Actual Weight kg"), get_row_value(row, "Estimated Weight kg"))
    estimated_book_weight_g = get_row_value(row, "Estimated Book Weight g")
    book_weight_evidence = get_row_value(row, "Book Weight Evidence")
    estimated_packaging_weight_kg = get_row_value(row, "Estimated Packaging Weight kg")
    packaging_materials = get_row_value(row, "Packaging Materials")
    packaging_weight_evidence = get_row_value(row, "Packaging Weight Evidence")
    dimensional_weight_kg = get_row_value(row, "Dimensional Weight kg")
    billable_weight_kg = get_row_value(row, "Billable Weight kg")
    billable_weight_source = get_row_value(row, "Billable Weight Source")
    package_length_cm = get_row_value(row, "Package Length cm")
    package_width_cm = get_row_value(row, "Package Width cm")
    package_height_cm = get_row_value(row, "Package Height cm")
    package_dimension_source = get_row_value(row, "Package Dimension Source")
    base_shipping_jpy = get_row_value(row, "FICP Base Shipping JPY")
    base_shipping_usd = get_row_value(row, "FICP Base Shipping USD")
    fuel_surcharge_percent = get_row_value(row, "FICP Fuel Surcharge Percent")
    fuel_surcharge_jpy = get_row_value(row, "FICP Fuel Surcharge JPY")
    fuel_surcharge_usd = get_row_value(row, "FICP Fuel Surcharge USD")
    shipping_jpy = get_row_value(row, "FICP Shipping JPY")
    shipping_usd = get_row_value(row, "FICP Shipping USD")
    eligibility = get_row_value(row, "Listing Eligibility")
    exclusion_reason = get_row_value(row, "Exclusion Reason")
    exclusion_evidence = get_row_value(row, "Exclusion Evidence")
    status = get_row_value(row, "Scrape Status")
    inferred_url = get_row_value(row, "Inferred Source URL")
    source_confidence = get_row_value(row, "Source URL Confidence")
    source_evidence = get_row_value(row, "Source URL Evidence")
    ai_status = get_row_value(row, "AI Enrichment Status")
    ai_provider = get_row_value(row, "AI Provider")
    ai_model = get_row_value(row, "AI Model")
    us_zone = get_row_value(row, "FICP US Zone")
    specifics_notes = get_row_value(row, "Specifics Fill Notes")
    description_added_text = get_row_value(row, "Description Added Text")
    description_added_japanese = get_row_value(row, "Description Added Japanese")
    description_notes = get_row_value(row, "Description Detail Notes")
    reference_book_count = get_row_value(row, "Reference Book Count")
    reference_count_source = get_row_value(row, "Reference Count Source")
    reference_count_confidence = get_row_value(row, "Reference Count Confidence")
    reference_count_evidence = get_row_value(row, "Reference Count Evidence")
    reference_count_status = get_row_value(row, "Reference Count Status")
    source_url = display_source_url(row, url_col)
    processed = bool(status or book_count or shipping_usd or specifics_notes)
    description_display = description_added_text or description_notes or (
        "処理済みです。Descriptionへ追記する状態説明は見つかりませんでした。"
        if processed
        else "まだ処理されていません。"
    )
    description_japanese_display = description_added_japanese or (
        "処理済みです。Descriptionへ追記する状態説明は見つかりませんでした。"
        if processed
        else "まだ処理されていません。"
    )

    if image_url:
        image_col_obj, detail_col_obj = st.columns([0.34, 0.66], gap="medium")
        with image_col_obj:
            st.markdown('<div class="image-shell">', unsafe_allow_html=True)
            st.image(image_url, use_container_width=True)
            st.markdown("</div>", unsafe_allow_html=True)
            render_additional_image_gallery(st, additional_image_urls)
        detail_container = detail_col_obj
    else:
        st.markdown(
            '<div class="compact-notice">画像プレビューは未取得です。商品情報を横幅いっぱいに表示しています。</div>',
            unsafe_allow_html=True,
        )
        detail_container = st.container()

    with detail_container:
        st.subheader(title)
        if eligibility.lower() == "excluded":
            st.error(
                "出品除外: 欠巻・欠品・欠損の可能性があるため、この商品はダウンロードCSVから自動で削除されます。"
            )
        render_preview_metric_cards(
            st,
            build_preview_metric_items(
                price=price,
                book_count=book_count,
                weight_kg=billable_weight_kg or actual_weight_kg,
                shipping_jpy=shipping_jpy,
                shipping_usd=shipping_usd,
            ),
        )
        st.markdown(
            f"""
            <div class="result-note">
            <strong>冊数の根拠:</strong> {html_escape(get_row_value(row, "Book Count Evidence") or "-")}<br>
            <strong>冊数判定:</strong> {html_escape(book_count_status or "-")}<br>
            <strong>参照冊数判定:</strong> {html_escape((reference_book_count + "冊") if reference_book_count else "-")} / {html_escape(reference_count_source or "-")} / 信頼度 {html_escape(reference_count_confidence or "-")} / {html_escape(reference_count_evidence or reference_count_status or "-")}<br>
            <strong>1冊重量:</strong> {html_escape((estimated_book_weight_g + "g") if estimated_book_weight_g else "-")} {html_escape("(" + book_weight_evidence + ")" if book_weight_evidence else "")}<br>
            <strong>梱包材:</strong> {html_escape(format_weight_display(estimated_packaging_weight_kg))} {html_escape("(" + packaging_materials + ")" if packaging_materials else "")}<br>
            <strong>梱包重量根拠:</strong> {html_escape(packaging_weight_evidence or "-")}<br>
            <strong>重量根拠:</strong> 実重量 {html_escape(format_weight_display(actual_weight_kg))} / 容積重量 {html_escape(format_weight_display(dimensional_weight_kg))} / 採用 {html_escape("容積重量" if billable_weight_source == "dimensional" else "実重量" if billable_weight_source == "actual" else "-")}<br>
            <strong>箱サイズ:</strong> {html_escape(package_length_cm or "-")} x {html_escape(package_width_cm or "-")} x {html_escape(package_height_cm or "-")} cm ({html_escape(package_dimension_source or "-")})<br>
            <strong>米国Zone:</strong> {html_escape(us_zone or "-")}<br>
            <strong>送料表:</strong> FedEx International Connect Plus Export (JPY)<br>
            <strong>FICP基本送料:</strong> {html_escape(format_jpy_display(base_shipping_jpy) or "-")} {html_escape("$" + base_shipping_usd if base_shipping_usd else "")}<br>
            <strong>燃油サーチャージ:</strong> {html_escape((fuel_surcharge_percent + "%") if fuel_surcharge_percent else "-")} / {html_escape(format_jpy_display(fuel_surcharge_jpy) or "-")} {html_escape("$" + fuel_surcharge_usd if fuel_surcharge_usd else "")}<br>
            <strong>送料合計:</strong> {html_escape(format_jpy_display(shipping_jpy) or "-")} {html_escape("$" + shipping_usd if shipping_usd else "")}<br>
            <strong>出品判定:</strong> {html_escape(eligibility or "-")}<br>
            <strong>除外理由:</strong> {html_escape(exclusion_reason or "-")}<br>
            <strong>除外根拠:</strong> {html_escape(exclusion_evidence or "-")}<br>
            <strong>取得状態:</strong> {html_escape(status or "-")}<br>
            <strong>AI補完:</strong> {html_escape(ai_status or "OFF")} {html_escape("(" + ai_provider + " / " + ai_model + ")" if ai_provider or ai_model else "")}<br>
            <strong>参照元:</strong> {f'<a href="{html_escape(source_url)}" target="_blank">{html_escape(source_url)}</a>' if source_url else "-"}<br>
            <strong>参照元判定:</strong> {html_escape(source_confidence or "-")} / {html_escape(source_evidence or "-")}
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown('<div class="section-title">メルカリ取得情報</div>', unsafe_allow_html=True)
    render_source_listing_info(st, row, processed)
    detail_col1, detail_col2 = st.columns([0.42, 0.58], gap="medium")
    with detail_col1:
        st.markdown('<div class="section-title">Description追記</div>', unsafe_allow_html=True)
        st.markdown(
            f'<div class="result-note"><strong>英語（CSVへ追記）</strong><br>{html_escape(description_display)}</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div class="result-note"><strong>日本語訳（確認用）</strong><br>{html_escape(description_japanese_display)}</div>',
            unsafe_allow_html=True,
        )
    with detail_col2:
        st.markdown('<div class="section-title">Specifics補完サマリー</div>', unsafe_allow_html=True)
        render_specifics_compact_summary(st, row, processed)
    st.markdown('<div class="section-title">Specifics項目別チェック</div>', unsafe_allow_html=True)
    render_specifics_review(st, row, processed)


if __name__ == "__main__":
    main()
