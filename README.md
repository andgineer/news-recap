# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/andgineer/news-recap/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                     |    Stmts |     Miss |   Cover |   Missing |
|--------------------------------------------------------- | -------: | -------: | ------: | --------: |
| src/news\_recap/\_\_about\_\_.py                         |        1 |        0 |    100% |           |
| src/news\_recap/config.py                                |      278 |       37 |     87% |251, 253, 255, 261, 269, 271, 291, 297, 299, 301, 303, 307, 309, 339, 346, 362, 364, 374-375, 379, 394, 406, 408, 416, 426, 438, 440, 459-464, 470, 480, 487, 494 |
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
| src/news\_recap/ingestion/repository.py                  |      531 |       99 |     81% |118, 147, 187, 212, 242, 258-263, 281, 310-320, 444, 467-469, 533-537, 605, 643, 749-751, 799, 830, 858, 881-884, 956-963, 1017-1037, 1166-1242, 1251-1257, 1375-1377, 1405, 1488, 1503-1509 |
| src/news\_recap/ingestion/services/dedup\_service.py     |       53 |        3 |     94% |    99-101 |
| src/news\_recap/ingestion/services/fetch\_service.py     |       65 |        2 |     97% |   79, 120 |
| src/news\_recap/ingestion/services/normalize\_service.py |       14 |        0 |    100% |           |
| src/news\_recap/ingestion/sources/base.py                |       31 |        3 |     90% |46, 55, 64 |
| src/news\_recap/ingestion/sources/rss.py                 |      424 |      116 |     73% |45, 56, 70, 81, 91, 100, 199, 324, 338, 351, 375-380, 401, 403, 414-454, 464-471, 480-503, 514-515, 521-522, 530-543, 594-632, 636-650, 660-662, 673-678, 682-685, 725, 730, 734, 753-754, 764, 772 |
| src/news\_recap/main.py                                  |       71 |        1 |     99% |       327 |
| src/news\_recap/recap/agent\_task.py                     |       35 |       18 |     49% |     42-86 |
| src/news\_recap/recap/backend/base.py                    |       24 |        0 |    100% |           |
| src/news\_recap/recap/backend/benchmark\_agent.py        |       88 |       88 |      0% |     3-149 |
| src/news\_recap/recap/backend/cli\_backend.py            |      169 |      101 |     40% |24-25, 32-88, 113-125, 151-202, 214, 227, 238-239, 246, 266-267, 286, 288, 292, 295, 306-307, 309, 331-375, 379-390 |
| src/news\_recap/recap/backend/echo\_agent.py             |       40 |       40 |      0% |     19-90 |
| src/news\_recap/recap/contracts.py                       |      116 |       43 |     63% |80, 93-103, 115-148, 154, 173, 177, 191, 207-208 |
| src/news\_recap/recap/flow.py                            |      128 |      109 |     15% |60-149, 162-207, 219-248, 256-257, 267-329 |
| src/news\_recap/recap/launcher.py                        |       54 |       29 |     46% |45-53, 65-99, 108-118 |
| src/news\_recap/recap/models.py                          |       18 |        2 |     89% |    23, 35 |
| src/news\_recap/recap/pipeline\_io.py                    |       60 |       38 |     37% |31-37, 42, 57-59, 69-72, 86-118, 123-147 |
| src/news\_recap/recap/prompts.py                         |       10 |        0 |    100% |           |
| src/news\_recap/recap/resource\_loader.py                |       43 |       21 |     51% |39-41, 46-48, 51-59, 68-90, 99-100, 103, 106 |
| src/news\_recap/recap/routing.py                         |      110 |       27 |     75% |54, 64, 85-115, 154, 159, 184, 219, 221, 224, 226, 229, 231, 233, 235, 237, 266 |
| src/news\_recap/recap/runner.py                          |      201 |       18 |     91% |46-53, 56, 65, 109, 130-134, 287, 290, 404, 442 |
| src/news\_recap/recap/schemas.py                         |        8 |        0 |    100% |           |
| src/news\_recap/recap/workdir.py                         |       55 |        0 |    100% |           |
| src/news\_recap/storage/alembic\_runner.py               |       12 |        0 |    100% |           |
| src/news\_recap/storage/common.py                        |       36 |        8 |     78% |24-27, 33-36 |
| src/news\_recap/storage/sqlmodel\_models.py              |      155 |        0 |    100% |           |
| **TOTAL**                                                | **3591** |  **929** | **74%** |           |


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