# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/andgineer/news-recap/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                     |    Stmts |     Miss |   Cover |   Missing |
|--------------------------------------------------------- | -------: | -------: | ------: | --------: |
| src/news\_recap/\_\_about\_\_.py                         |        1 |        0 |    100% |           |
| src/news\_recap/config.py                                |      262 |       47 |     82% |223, 227, 229, 235, 241, 244, 248, 263, 265, 267, 269, 273, 275, 303, 310, 326, 328, 338-339, 343, 396-413, 422, 424, 443-448, 454, 464, 471, 478 |
| src/news\_recap/http/fetcher.py                          |       42 |        4 |     90% |47, 92, 95, 98 |
| src/news\_recap/http/html\_extractor.py                  |       29 |        7 |     76% |47-49, 60-62, 69 |
| src/news\_recap/http/youtube\_extractor.py               |       74 |       45 |     39% |38, 42-43, 67, 81-92, 101-126, 149-170 |
| src/news\_recap/ingestion/cleaning.py                    |       53 |        1 |     98% |        75 |
| src/news\_recap/ingestion/controllers.py                 |      120 |        8 |     93% |138, 160, 184, 207, 227, 265-266, 302 |
| src/news\_recap/ingestion/dedup/calibration.py           |       66 |       32 |     52% |71-95, 105-107, 113-143 |
| src/news\_recap/ingestion/dedup/cluster.py               |       74 |        4 |     95% |20, 58, 62, 128 |
| src/news\_recap/ingestion/dedup/embedder.py              |       71 |       14 |     80% |27-30, 40, 58, 61, 83-86, 89-91, 118 |
| src/news\_recap/ingestion/language.py                    |       23 |        2 |     91% |    21, 35 |
| src/news\_recap/ingestion/models.py                      |      191 |        0 |    100% |           |
| src/news\_recap/ingestion/pipeline.py                    |       39 |        0 |    100% |           |
| src/news\_recap/ingestion/repository.py                  |      329 |       28 |     91% |97, 139, 212, 226, 228, 238-243, 256, 282-289, 342, 420, 582, 600, 606, 709-712 |
| src/news\_recap/ingestion/services/dedup\_service.py     |       49 |        3 |     94% |    99-101 |
| src/news\_recap/ingestion/services/fetch\_service.py     |       65 |        2 |     97% |   79, 120 |
| src/news\_recap/ingestion/services/normalize\_service.py |       14 |        0 |    100% |           |
| src/news\_recap/ingestion/sources/base.py                |       31 |        3 |     90% |46, 55, 64 |
| src/news\_recap/ingestion/sources/rss.py                 |      424 |      116 |     73% |45, 56, 70, 81, 91, 100, 199, 324, 338, 351, 375-380, 401, 403, 414-454, 464-471, 480-503, 514-515, 521-522, 530-543, 594-632, 636-650, 660-662, 673-678, 682-685, 725, 730, 734, 753-754, 764, 772 |
| src/news\_recap/main.py                                  |       61 |        1 |     98% |       301 |
| src/news\_recap/recap/agents/ai\_agent.py                |      101 |       80 |     21% |54-94, 99-109, 125-171, 199-211, 236-287 |
| src/news\_recap/recap/agents/benchmark.py                |       88 |       88 |      0% |     3-149 |
| src/news\_recap/recap/agents/echo.py                     |       40 |       40 |      0% |     19-90 |
| src/news\_recap/recap/agents/routing.py                  |       94 |       17 |     82% |40, 52-60, 88, 114, 119, 143, 175, 177, 180, 182, 184, 186, 188 |
| src/news\_recap/recap/agents/subprocess.py               |      109 |       39 |     64% |22-23, 57, 68, 80-81, 88, 105-106, 125, 127, 131, 134, 145-146, 148, 172-205, 209-220 |
| src/news\_recap/recap/contracts.py                       |      116 |       43 |     63% |80, 93-103, 115-148, 154, 173, 177, 191, 207-208 |
| src/news\_recap/recap/flow.py                            |       78 |       54 |     31% |45-48, 55-56, 70-145 |
| src/news\_recap/recap/launcher.py                        |       81 |       51 |     37% |29, 64-95, 109-118, 130-191 |
| src/news\_recap/recap/loaders/resource\_cache.py         |       52 |        0 |    100% |           |
| src/news\_recap/recap/loaders/resource\_loader.py        |      123 |       13 |     89% |85, 174-180, 184-186, 208, 219, 265, 274-275, 278, 281 |
| src/news\_recap/recap/models.py                          |       56 |        8 |     86% |24-29, 32, 41 |
| src/news\_recap/recap/storage/pipeline\_io.py            |      155 |       36 |     77% |36-43, 48, 77-80, 93-96, 112-134, 145-151, 174, 180-181, 195, 244, 255, 290 |
| src/news\_recap/recap/storage/schemas.py                 |        4 |        0 |    100% |           |
| src/news\_recap/recap/storage/workdir.py                 |       55 |        0 |    100% |           |
| src/news\_recap/recap/tasks/base.py                      |       76 |       15 |     80% |100, 123-139, 142 |
| src/news\_recap/recap/tasks/classify.py                  |      177 |       74 |     58% |136, 142, 220-231, 234-262, 271-330, 334-348 |
| src/news\_recap/recap/tasks/compose.py                   |       19 |        9 |     53% |     24-50 |
| src/news\_recap/recap/tasks/enrich.py                    |      217 |       34 |     84% |142-143, 145-146, 208, 255-256, 311-320, 365-372, 385, 398-399, 433, 455-462, 473-489 |
| src/news\_recap/recap/tasks/group.py                     |       33 |       11 |     67% |     60-82 |
| src/news\_recap/recap/tasks/load\_resources.py           |       57 |        6 |     89% |44, 86-87, 93-95 |
| src/news\_recap/recap/tasks/prompts.py                   |        7 |        0 |    100% |           |
| src/news\_recap/recap/tasks/synthesize.py                |       18 |        8 |     56% |     24-44 |
| src/news\_recap/storage/io.py                            |       42 |        6 |     86% |33-36, 59, 73 |
| **TOTAL**                                                | **3816** |  **949** | **75%** |           |


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