# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/andgineer/news-recap/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                     |    Stmts |     Miss |   Cover |   Missing |
|--------------------------------------------------------- | -------: | -------: | ------: | --------: |
| src/news\_recap/\_\_about\_\_.py                         |        1 |        0 |    100% |           |
| src/news\_recap/config.py                                |      247 |       40 |     84% |277, 279, 281, 287, 295, 297, 317, 323, 325, 327, 329, 333, 335, 337, 339, 341, 343, 345, 375, 382, 398, 400, 410-411, 415, 429, 438, 440, 448, 458, 470, 472, 491-496, 502, 532 |
| src/news\_recap/ingestion/cleaning.py                    |       53 |        4 |     92% |41, 45-46, 75 |
| src/news\_recap/ingestion/controllers.py                 |      154 |       12 |     92% |143, 172, 194, 218, 241, 261, 293, 302, 338-339, 377, 388 |
| src/news\_recap/ingestion/dedup/calibration.py           |       66 |       32 |     52% |71-95, 105-107, 113-143 |
| src/news\_recap/ingestion/dedup/cluster.py               |       74 |        4 |     95% |20, 58, 62, 128 |
| src/news\_recap/ingestion/dedup/embedder.py              |       71 |       14 |     80% |27-30, 40, 58, 61, 83-86, 89-91, 118 |
| src/news\_recap/ingestion/language.py                    |       23 |        2 |     91% |    21, 35 |
| src/news\_recap/ingestion/models.py                      |      161 |        0 |    100% |           |
| src/news\_recap/ingestion/pipeline.py                    |       39 |        0 |    100% |           |
| src/news\_recap/ingestion/repository.py                  |      483 |       59 |     88% |115, 144, 184, 209, 239, 255-260, 278, 307-317, 441, 464-466, 530-534, 602, 640, 746-748, 796, 827, 855, 878-881, 953-960, 1014-1034, 1255-1257, 1285, 1368 |
| src/news\_recap/ingestion/services/dedup\_service.py     |       51 |        3 |     94% |     97-99 |
| src/news\_recap/ingestion/services/fetch\_service.py     |       65 |        2 |     97% |   79, 120 |
| src/news\_recap/ingestion/services/normalize\_service.py |       14 |        0 |    100% |           |
| src/news\_recap/ingestion/sources/base.py                |       31 |        3 |     90% |46, 55, 64 |
| src/news\_recap/ingestion/sources/rss.py                 |      419 |      113 |     73% |45, 56, 70, 81, 91, 100, 199, 324, 338, 351, 375-380, 401, 403, 414-454, 464-471, 480-503, 514-515, 521-522, 530-543, 594-632, 636-650, 668-673, 677-680, 720, 725, 729, 748-749, 759, 767 |
| src/news\_recap/ingestion/storage/alembic\_runner.py     |       12 |        0 |    100% |           |
| src/news\_recap/ingestion/storage/common.py              |       36 |        8 |     78% |24-27, 33-36 |
| src/news\_recap/ingestion/storage/sqlmodel\_models.py    |      342 |        0 |    100% |           |
| src/news\_recap/main.py                                  |      279 |       10 |     96% |699, 715, 886, 1056, 1105, 1131, 1196, 1319, 1361, 1391 |
| src/news\_recap/orchestrator/backend/base.py             |       24 |        0 |    100% |           |
| src/news\_recap/orchestrator/backend/benchmark\_agent.py |       80 |       80 |      0% |     3-127 |
| src/news\_recap/orchestrator/backend/cli\_backend.py     |      141 |       24 |     83% |83-84, 140, 160, 173-174, 181, 201-202, 221, 223, 227, 230, 241-242, 244, 314-315, 318-323 |
| src/news\_recap/orchestrator/backend/echo\_agent.py      |       19 |        0 |    100% |           |
| src/news\_recap/orchestrator/contracts.py                |      112 |       16 |     86% |77, 95, 97, 99, 115, 120, 127, 129, 131, 133, 135, 170, 174, 185, 206-207 |
| src/news\_recap/orchestrator/controllers.py              |      285 |       23 |     92% |373, 406-409, 412-415, 423-426, 444, 465, 525-526, 534, 543, 565, 608, 624, 642 |
| src/news\_recap/orchestrator/failure\_classifier.py      |       42 |        2 |     95% |  100, 127 |
| src/news\_recap/orchestrator/intelligence.py             |      335 |       88 |     74% |168-178, 193-195, 237, 310-400, 407-418, 425-434, 437-487, 538-550, 555-568, 574-579, 637, 641-644, 646-658, 706, 735, 822 |
| src/news\_recap/orchestrator/metrics.py                  |      203 |       46 |     77% |37-39, 86-90, 116-119, 142-145, 150, 154-156, 266-268, 295, 320, 398, 405-406, 413-414, 423, 443, 447-453, 477-481, 487, 495 |
| src/news\_recap/orchestrator/models.py                   |      292 |        0 |    100% |           |
| src/news\_recap/orchestrator/output\_fallback.py         |       89 |       16 |     82% |24, 34, 37, 55, 67, 76, 87, 90, 95, 98, 105, 107, 111, 115, 119, 127 |
| src/news\_recap/orchestrator/pricing.py                  |       51 |        5 |     90% |41, 76, 79, 84-85 |
| src/news\_recap/orchestrator/repair.py                   |       14 |        1 |     93% |        30 |
| src/news\_recap/orchestrator/repository.py               |      624 |      119 |     81% |214-215, 240, 271, 280, 302, 324-338, 358-359, 474, 588, 611, 645-646, 673, 677, 785, 800, 895, 898, 900, 990, 992, 994, 996, 1015, 1017, 1039, 1109, 1131, 1172-1177, 1207-1236, 1245-1254, 1384-1392, 1420-1437, 1458, 1461, 1516-1531, 1561-1562, 1564, 1573-1635, 1668, 1744, 1753, 1780, 1796, 1830-1839, 1865-1873, 1902, 1968-1969, 2021, 2039-2040, 2061-2062, 2067-2068, 2100, 2103 |
| src/news\_recap/orchestrator/routing.py                  |      104 |       16 |     85% |65, 83, 85, 123, 128, 153, 188, 190, 193, 195, 198, 200, 202, 204, 206, 235 |
| src/news\_recap/orchestrator/sanitization.py             |       16 |        1 |     94% |        52 |
| src/news\_recap/orchestrator/services.py                 |       49 |        0 |    100% |           |
| src/news\_recap/orchestrator/smoke.py                    |      111 |       41 |     63% |72-89, 92-105, 146-149, 156, 176-192, 208, 211, 220-223, 228, 230, 240-255, 262 |
| src/news\_recap/orchestrator/usage.py                    |       91 |        3 |     97% |137, 140-141 |
| src/news\_recap/orchestrator/validator.py                |       37 |        5 |     86% |49, 57, 65, 74, 89 |
| src/news\_recap/orchestrator/workdir.py                  |       42 |        0 |    100% |           |
| src/news\_recap/orchestrator/worker.py                   |      511 |       97 |     81% |148-149, 178-180, 214, 216, 231, 236, 241, 252-253, 272, 299-311, 327, 406, 418-433, 455, 457, 540-541, 544-556, 626, 629-648, 724-744, 782-784, 789-790, 796-800, 820, 822, 842, 844, 899, 999, 1004, 1008, 1065, 1078, 1081, 1087, 1102-1109, 1117-1118, 1120, 1123, 1127, 1136, 1139, 1141, 1144-1145, 1151, 1161, 1164, 1166, 1182, 1208, 1215-1218, 1226, 1283, 1288 |
| **TOTAL**                                                | **5893** |  **889** | **85%** |           |


## Setup coverage badge

Below are examples of the badges you can use in your main branch `README` file.

### Direct image

[![Coverage badge](https://raw.githubusercontent.com/andgineer/news-recap/python-coverage-comment-action-data/badge.svg)](https://htmlpreview.github.io/?https://github.com/andgineer/news-recap/blob/python-coverage-comment-action-data/htmlcov/index.html)

This is the one to use if your repository is private or if you don't want to customize anything.

### [Shields.io](https://shields.io) Json Endpoint

[![Coverage badge](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/andgineer/news-recap/python-coverage-comment-action-data/endpoint.json)](https://htmlpreview.github.io/?https://github.com/andgineer/news-recap/blob/python-coverage-comment-action-data/htmlcov/index.html)

Using this one will allow you to [customize](https://shields.io/endpoint) the look of your badge.
It won't work with private repositories. It won't be refreshed more than once per five minutes.

### [Shields.io](https://shields.io) Dynamic Badge

[![Coverage badge](https://img.shields.io/badge/dynamic/json?color=brightgreen&label=coverage&query=%24.message&url=https%3A%2F%2Fraw.githubusercontent.com%2Fandgineer%2Fnews-recap%2Fpython-coverage-comment-action-data%2Fendpoint.json)](https://htmlpreview.github.io/?https://github.com/andgineer/news-recap/blob/python-coverage-comment-action-data/htmlcov/index.html)

This one will always be the same color. It won't work for private repos. I'm not even sure why we included it.

## What is that?

This branch is part of the
[python-coverage-comment-action](https://github.com/marketplace/actions/python-coverage-comment)
GitHub Action. All the files in this branch are automatically generated and may be
overwritten at any moment.