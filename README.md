# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/andgineer/news-recap/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                     |    Stmts |     Miss |   Cover |   Missing |
|--------------------------------------------------------- | -------: | -------: | ------: | --------: |
| src/news\_recap/\_\_about\_\_.py                         |        1 |        0 |    100% |           |
| src/news\_recap/config.py                                |      271 |       37 |     86% |234, 238, 240, 246, 254, 256, 276, 282, 284, 286, 288, 292, 294, 322, 329, 345, 347, 357-358, 362, 377, 389, 391, 399, 409, 421, 423, 442-447, 453, 463, 470, 477 |
| src/news\_recap/http/fetcher.py                          |       42 |       20 |     52% |42-48, 58-81, 91, 94, 97 |
| src/news\_recap/http/html\_extractor.py                  |       29 |        9 |     69% |47-49, 52-62, 69 |
| src/news\_recap/http/youtube\_extractor.py               |       49 |       29 |     41% |    57-107 |
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
| src/news\_recap/recap/agent\_benchmark.py                |       88 |       88 |      0% |     3-149 |
| src/news\_recap/recap/agent\_echo.py                     |       40 |       40 |      0% |     19-90 |
| src/news\_recap/recap/contracts.py                       |      116 |       43 |     63% |80, 93-103, 115-148, 154, 173, 177, 191, 207-208 |
| src/news\_recap/recap/flow.py                            |       75 |       52 |     31% |41-44, 51-52, 66-139 |
| src/news\_recap/recap/launcher.py                        |       50 |       26 |     48% |47-57, 69-111 |
| src/news\_recap/recap/models.py                          |       33 |        0 |    100% |           |
| src/news\_recap/recap/pipeline\_io.py                    |       61 |       38 |     38% |33-39, 44, 59-61, 71-74, 88-120, 125-149 |
| src/news\_recap/recap/prompts.py                         |       10 |        0 |    100% |           |
| src/news\_recap/recap/resource\_loader.py                |       43 |       21 |     51% |39-41, 46-48, 51-59, 68-90, 99-100, 103, 106 |
| src/news\_recap/recap/routing.py                         |      108 |       27 |     75% |43, 47, 55-85, 124, 129, 154, 189, 191, 194, 196, 199, 201, 203, 205, 207, 236 |
| src/news\_recap/recap/runner.py                          |      201 |       18 |     91% |47-54, 57, 61, 100, 121-125, 278, 281, 395, 433 |
| src/news\_recap/recap/schemas.py                         |        8 |        0 |    100% |           |
| src/news\_recap/recap/task\_ai\_agent.py                 |       92 |       70 |     24% |57-96, 112-160, 188-200, 225-276 |
| src/news\_recap/recap/task\_base.py                      |       43 |       12 |     72% |51, 60, 65-76, 79 |
| src/news\_recap/recap/task\_classify.py                  |       50 |       38 |     24% |     30-94 |
| src/news\_recap/recap/task\_compose.py                   |       17 |        8 |     53% |     19-39 |
| src/news\_recap/recap/task\_enrich.py                    |       41 |       26 |     37% |37-59, 68-74, 91-111 |
| src/news\_recap/recap/task\_group.py                     |       20 |       11 |     45% |     23-43 |
| src/news\_recap/recap/task\_subprocess.py                |      109 |       39 |     64% |22-23, 56, 67, 76-77, 84, 101-102, 121, 123, 127, 130, 141-142, 144, 168-201, 205-216 |
| src/news\_recap/recap/task\_synthesize.py                |       17 |        8 |     53% |     19-37 |
| src/news\_recap/recap/workdir.py                         |       55 |        0 |    100% |           |
| src/news\_recap/storage/io.py                            |       42 |        6 |     86% |33-36, 59, 73 |
| **TOTAL**                                                | **3320** |  **880** | **73%** |           |


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