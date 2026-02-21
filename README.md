# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/andgineer/news-recap/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                     |    Stmts |     Miss |   Cover |   Missing |
|--------------------------------------------------------- | -------: | -------: | ------: | --------: |
| src/news\_recap/\_\_about\_\_.py                         |        1 |        0 |    100% |           |
| src/news\_recap/agent\_runtime.py                        |       73 |       22 |     70% |37, 40-41, 46, 126, 128, 156-185 |
| src/news\_recap/brain/backend/base.py                    |       24 |        0 |    100% |           |
| src/news\_recap/brain/backend/benchmark\_agent.py        |       88 |       88 |      0% |     3-149 |
| src/news\_recap/brain/backend/cli\_backend.py            |      165 |       62 |     62% |24-25, 77-83, 111, 114, 146-197, 209, 222, 233-234, 241, 261-262, 281, 283, 287, 290, 301-302, 304, 350-351, 359-363, 374-385 |
| src/news\_recap/brain/backend/echo\_agent.py             |       24 |       24 |      0% |      3-48 |
| src/news\_recap/brain/contracts.py                       |      116 |       35 |     70% |80, 98, 100, 102, 115-148, 154, 173, 177, 191, 207-208 |
| src/news\_recap/brain/flows.py                           |      390 |       99 |     75% |183-193, 208-210, 251, 293-354, 362-373, 380-389, 392-435, 478-490, 495-508, 514-519, 635-638, 691-694, 785, 807, 811, 836-837, 865, 869-872, 874-886, 934, 968, 1075 |
| src/news\_recap/brain/models.py                          |      127 |        0 |    100% |           |
| src/news\_recap/brain/pricing.py                         |       51 |        5 |     90% |41, 76, 79, 84-85 |
| src/news\_recap/brain/routing.py                         |      104 |       25 |     76% |58-88, 123, 128, 153, 188, 190, 193, 195, 198, 200, 202, 204, 206, 235 |
| src/news\_recap/brain/sanitization.py                    |       16 |        2 |     88% |    44, 52 |
| src/news\_recap/brain/usage.py                           |       91 |       29 |     68% |38, 42, 63-66, 89-91, 95-96, 100-101, 105-107, 109, 114-121, 135-141 |
| src/news\_recap/brain/workdir.py                         |       55 |        0 |    100% |           |
| src/news\_recap/config.py                                |      293 |       42 |     86% |248, 250, 252, 258, 266, 268, 288, 301, 303, 305, 307, 311, 313, 315, 317, 319, 321, 323, 353, 360, 376, 378, 388-389, 393, 409, 424, 426, 434, 444, 456, 458, 477-482, 488, 498, 505, 512 |
| src/news\_recap/http/fetcher.py                          |       42 |       20 |     52% |42-48, 58-81, 91, 94, 97 |
| src/news\_recap/http/html\_extractor.py                  |       29 |        9 |     69% |47-49, 52-62, 69 |
| src/news\_recap/http/youtube\_extractor.py               |       49 |       29 |     41% |    57-107 |
| src/news\_recap/ingestion/cleaning.py                    |       53 |        4 |     92% |41, 45-46, 75 |
| src/news\_recap/ingestion/controllers.py                 |      154 |       12 |     92% |143, 172, 194, 218, 241, 261, 293, 302, 338-339, 377, 388 |
| src/news\_recap/ingestion/dedup/calibration.py           |       66 |       32 |     52% |71-95, 105-107, 113-143 |
| src/news\_recap/ingestion/dedup/cluster.py               |       74 |        4 |     95% |20, 58, 62, 128 |
| src/news\_recap/ingestion/dedup/embedder.py              |       71 |       14 |     80% |27-30, 40, 58, 61, 83-86, 89-91, 118 |
| src/news\_recap/ingestion/language.py                    |       23 |        2 |     91% |    21, 35 |
| src/news\_recap/ingestion/models.py                      |      161 |        0 |    100% |           |
| src/news\_recap/ingestion/pipeline.py                    |       39 |        0 |    100% |           |
| src/news\_recap/ingestion/repository.py                  |      748 |      133 |     82% |140, 169, 209, 234, 264, 280-285, 303, 332-342, 466, 489-491, 555-559, 627, 665, 771-773, 821, 852, 880, 903-906, 978-985, 1039-1059, 1227, 1249, 1308-1313, 1468-1476, 1483-1512, 1521-1530, 1560-1577, 1598, 1601, 1658-1673, 1703-1704, 1706, 1717-1779, 1798, 1807, 1834, 1882-1891, 2032-2034, 2062, 2145, 2179, 2197-2198, 2219-2220, 2225-2226, 2258, 2261 |
| src/news\_recap/ingestion/services/dedup\_service.py     |       53 |        3 |     94% |    99-101 |
| src/news\_recap/ingestion/services/fetch\_service.py     |       65 |        2 |     97% |   79, 120 |
| src/news\_recap/ingestion/services/normalize\_service.py |       14 |        0 |    100% |           |
| src/news\_recap/ingestion/sources/base.py                |       31 |        3 |     90% |46, 55, 64 |
| src/news\_recap/ingestion/sources/rss.py                 |      424 |      116 |     73% |45, 56, 70, 81, 91, 100, 199, 324, 338, 351, 375-380, 401, 403, 414-454, 464-471, 480-503, 514-515, 521-522, 530-543, 594-632, 636-650, 660-662, 673-678, 682-685, 725, 730, 734, 753-754, 764, 772 |
| src/news\_recap/ingestion/storage/alembic\_runner.py     |       12 |        0 |    100% |           |
| src/news\_recap/ingestion/storage/common.py              |       36 |        8 |     78% |24-27, 33-36 |
| src/news\_recap/ingestion/storage/sqlmodel\_models.py    |      250 |        0 |    100% |           |
| src/news\_recap/main.py                                  |      194 |        9 |     95% |367, 537, 586, 612, 677, 800, 842, 872, 948 |
| src/news\_recap/recap/controllers.py                     |       86 |       59 |     31% |45-106, 110-128, 133-143 |
| src/news\_recap/recap/prefect\_flow.py                   |      133 |       88 |     34% |78-138, 165, 177, 180, 191-214, 225-249, 259-266, 287-338 |
| src/news\_recap/recap/prompts.py                         |        9 |        0 |    100% |           |
| src/news\_recap/recap/resource\_loader.py                |       43 |       21 |     51% |39-41, 46-48, 51-59, 68-90, 99-100, 103, 106 |
| src/news\_recap/recap/runner.py                          |      124 |       16 |     87% |42-49, 78-79, 88, 109-113, 227, 265 |
| src/news\_recap/recap/schemas.py                         |        8 |        0 |    100% |           |
| **TOTAL**                                                | **4609** | **1017** | **78%** |           |


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