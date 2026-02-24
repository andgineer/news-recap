# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/andgineer/news-recap/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                     |    Stmts |     Miss |   Cover |   Missing |
|--------------------------------------------------------- | -------: | -------: | ------: | --------: |
| src/news\_recap/\_\_about\_\_.py                         |        1 |        0 |    100% |           |
| src/news\_recap/config.py                                |      272 |       37 |     86% |236, 240, 242, 248, 256, 258, 278, 284, 286, 288, 290, 294, 296, 324, 331, 347, 349, 359-360, 364, 379, 391, 393, 401, 411, 423, 425, 444-449, 455, 465, 472, 479 |
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
| src/news\_recap/main.py                                  |       60 |        1 |     98% |       294 |
| src/news\_recap/recap/agents/ai\_agent.py                |      115 |       92 |     20% |59-104, 120-129, 134-144, 160-207, 235-247, 272-323 |
| src/news\_recap/recap/agents/benchmark.py                |       88 |       88 |      0% |     3-149 |
| src/news\_recap/recap/agents/echo.py                     |       40 |       40 |      0% |     19-90 |
| src/news\_recap/recap/agents/routing.py                  |      108 |       26 |     76% |43, 55-85, 124, 129, 154, 189, 191, 194, 196, 199, 201, 203, 205, 207, 236 |
| src/news\_recap/recap/agents/subprocess.py               |      109 |       39 |     64% |22-23, 57, 68, 80-81, 88, 105-106, 125, 127, 131, 134, 145-146, 148, 172-205, 209-220 |
| src/news\_recap/recap/contracts.py                       |      116 |       43 |     63% |80, 93-103, 115-148, 154, 173, 177, 191, 207-208 |
| src/news\_recap/recap/flow.py                            |       74 |       52 |     30% |41-44, 51-52, 66-139 |
| src/news\_recap/recap/launcher.py                        |       52 |       27 |     48% |25, 73-84, 96-139 |
| src/news\_recap/recap/loaders/resource\_cache.py         |       52 |        0 |    100% |           |
| src/news\_recap/recap/loaders/resource\_loader.py        |      123 |       13 |     89% |85, 174-180, 184-186, 208, 219, 265, 274-275, 278, 281 |
| src/news\_recap/recap/models.py                          |       56 |        8 |     86% |24-29, 32, 41 |
| src/news\_recap/recap/storage/pipeline\_io.py            |      117 |       51 |     56% |36-43, 48, 77-80, 94-126, 155, 164-165, 224-262 |
| src/news\_recap/recap/storage/schemas.py                 |        8 |        0 |    100% |           |
| src/news\_recap/recap/storage/workdir.py                 |       55 |        0 |    100% |           |
| src/news\_recap/recap/tasks/base.py                      |       71 |       13 |     82% |100, 109, 114-126, 129 |
| src/news\_recap/recap/tasks/classify.py                  |      150 |       53 |     65% |131, 137, 215-226, 229-294 |
| src/news\_recap/recap/tasks/compose.py                   |       16 |        8 |     50% |     22-42 |
| src/news\_recap/recap/tasks/enrich.py                    |      157 |       99 |     37% |58-89, 94-99, 114-152, 198, 235-299, 308-312, 325-344 |
| src/news\_recap/recap/tasks/group.py                     |       31 |       11 |     65% |     58-78 |
| src/news\_recap/recap/tasks/prompts.py                   |       10 |        0 |    100% |           |
| src/news\_recap/recap/tasks/synthesize.py                |       16 |        8 |     50% |     22-40 |
| src/news\_recap/storage/io.py                            |       42 |        6 |     86% |33-36, 59, 73 |
| **TOTAL**                                                | **3633** |  **984** | **73%** |           |


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