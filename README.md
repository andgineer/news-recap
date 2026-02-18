# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/andgineer/news-recap/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                     |    Stmts |     Miss |   Cover |   Missing |
|--------------------------------------------------------- | -------: | -------: | ------: | --------: |
| src/news\_recap/\_\_about\_\_.py                         |        1 |        0 |    100% |           |
| src/news\_recap/config.py                                |      133 |       15 |     89% |208, 215, 231, 233, 243-244, 248, 262, 264, 283-288 |
| src/news\_recap/ingestion/cleaning.py                    |       53 |        4 |     92% |41, 45-46, 75 |
| src/news\_recap/ingestion/controllers.py                 |      145 |       12 |     92% |135, 163, 185, 209, 232, 252, 284, 293, 316-317, 354, 365 |
| src/news\_recap/ingestion/dedup/calibration.py           |       66 |       32 |     52% |71-95, 105-107, 113-143 |
| src/news\_recap/ingestion/dedup/cluster.py               |       74 |        4 |     95% |20, 58, 62, 128 |
| src/news\_recap/ingestion/dedup/embedder.py              |       71 |       14 |     80% |27-30, 40, 58, 61, 83-86, 89-91, 118 |
| src/news\_recap/ingestion/language.py                    |       23 |        2 |     91% |    21, 35 |
| src/news\_recap/ingestion/models.py                      |      154 |        0 |    100% |           |
| src/news\_recap/ingestion/pipeline.py                    |       39 |        0 |    100% |           |
| src/news\_recap/ingestion/repository.py                  |      488 |       67 |     86% |103, 132, 172, 197, 227, 243-248, 266, 295-305, 429, 452-454, 533-537, 605, 643, 749-751, 799, 830, 858, 881-884, 956-963, 1017-1037, 1040-1061, 1222-1224, 1252, 1341 |
| src/news\_recap/ingestion/services/dedup\_service.py     |       51 |        3 |     94% |     97-99 |
| src/news\_recap/ingestion/services/fetch\_service.py     |       65 |        2 |     97% |   79, 120 |
| src/news\_recap/ingestion/services/normalize\_service.py |       14 |        0 |    100% |           |
| src/news\_recap/ingestion/sources/base.py                |       31 |        3 |     90% |46, 55, 64 |
| src/news\_recap/ingestion/sources/rss.py                 |      419 |      113 |     73% |45, 56, 70, 81, 91, 100, 199, 324, 338, 351, 375-380, 401, 403, 414-454, 464-471, 480-503, 514-515, 521-522, 530-543, 594-632, 636-650, 668-673, 677-680, 720, 725, 729, 748-749, 759, 767 |
| src/news\_recap/ingestion/storage/alembic\_runner.py     |       12 |        0 |    100% |           |
| src/news\_recap/ingestion/storage/common.py              |       15 |        8 |     47% |18-21, 27-30 |
| src/news\_recap/ingestion/storage/sqlmodel\_models.py    |      201 |        0 |    100% |           |
| src/news\_recap/main.py                                  |      106 |        2 |     98% |  419, 435 |
| src/news\_recap/orchestrator/backend/base.py             |       17 |        0 |    100% |           |
| src/news\_recap/orchestrator/backend/cli\_backend.py     |       47 |       13 |     72% |19-20, 66-79, 88, 91-93, 97 |
| src/news\_recap/orchestrator/backend/echo\_agent.py      |       19 |        0 |    100% |           |
| src/news\_recap/orchestrator/contracts.py                |       95 |       13 |     86% |72, 90, 92, 94, 110, 115, 121, 123, 125, 127, 161, 173-174 |
| src/news\_recap/orchestrator/controllers.py              |      134 |       12 |     91% |157, 180-183, 186-189, 196, 251, 267 |
| src/news\_recap/orchestrator/models.py                   |       71 |        0 |    100% |           |
| src/news\_recap/orchestrator/repair.py                   |       14 |        2 |     86% |    30, 35 |
| src/news\_recap/orchestrator/repository.py               |      194 |       30 |     85% |78-85, 147, 170-171, 190-204, 224-225, 289, 393, 427-428, 455, 459, 476-477, 523, 574-582, 617 |
| src/news\_recap/orchestrator/services.py                 |       25 |        0 |    100% |           |
| src/news\_recap/orchestrator/smoke.py                    |       93 |       26 |     72% |71-84, 87-100, 135-138, 145, 163-173, 188, 190, 199-202, 207, 209, 222 |
| src/news\_recap/orchestrator/validator.py                |       37 |        8 |     78% |31, 40-41, 49, 57, 65, 74, 89 |
| src/news\_recap/orchestrator/workdir.py                  |       30 |        0 |    100% |           |
| src/news\_recap/orchestrator/worker.py                   |      160 |       73 |     54% |73-74, 82-92, 102-134, 136-152, 155-185, 201-210, 231-237, 253-269, 324-347, 350-354 |
| **TOTAL**                                                | **3097** |  **458** | **85%** |           |


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