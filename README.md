# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/andgineer/news-recap/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                     |    Stmts |     Miss |   Cover |   Missing |
|--------------------------------------------------------- | -------: | -------: | ------: | --------: |
| src/news\_recap/\_\_about\_\_.py                         |        1 |        0 |    100% |           |
| src/news\_recap/config.py                                |      120 |       15 |     88% |156, 163, 179, 181, 191-192, 196, 210, 212, 231-236 |
| src/news\_recap/ingestion/cleaning.py                    |       53 |        4 |     92% |41, 45-46, 75 |
| src/news\_recap/ingestion/controllers.py                 |      145 |       12 |     92% |133, 161, 183, 207, 230, 250, 282, 291, 314-315, 352, 363 |
| src/news\_recap/ingestion/dedup/calibration.py           |       66 |       32 |     52% |71-95, 105-107, 113-143 |
| src/news\_recap/ingestion/dedup/cluster.py               |       74 |        4 |     95% |20, 58, 62, 128 |
| src/news\_recap/ingestion/dedup/embedder.py              |       71 |       14 |     80% |27-30, 40, 58, 61, 83-86, 89-91, 118 |
| src/news\_recap/ingestion/language.py                    |       23 |        2 |     91% |    21, 35 |
| src/news\_recap/ingestion/models.py                      |      154 |        0 |    100% |           |
| src/news\_recap/ingestion/pipeline.py                    |       39 |        0 |    100% |           |
| src/news\_recap/ingestion/repository.py                  |      409 |       41 |     90% |101, 130, 170, 195, 225, 241-246, 264, 293-303, 506-508, 567, 605, 711-713, 761, 791, 820, 845-848, 910-915, 996-998, 1027, 1118 |
| src/news\_recap/ingestion/services/dedup\_service.py     |       51 |        3 |     94% |     97-99 |
| src/news\_recap/ingestion/services/fetch\_service.py     |       65 |        2 |     97% |   79, 119 |
| src/news\_recap/ingestion/services/normalize\_service.py |       14 |        0 |    100% |           |
| src/news\_recap/ingestion/sources/base.py                |       31 |        3 |     90% |46, 55, 64 |
| src/news\_recap/ingestion/sources/rss.py                 |      413 |      113 |     73% |45, 56, 70, 81, 91, 100, 197, 314, 328, 341, 365-370, 391, 393, 404-444, 454-461, 470-493, 504-505, 511-512, 520-533, 584-622, 626-640, 658-663, 667-670, 710, 715, 719, 738-739, 749, 757 |
| src/news\_recap/ingestion/storage/alembic\_runner.py     |       12 |        0 |    100% |           |
| src/news\_recap/ingestion/storage/common.py              |       15 |        8 |     47% |18-21, 27-30 |
| src/news\_recap/ingestion/storage/sqlmodel\_models.py    |      137 |        0 |    100% |           |
| src/news\_recap/main.py                                  |       52 |        0 |    100% |           |
| **TOTAL**                                                | **1945** |  **253** | **87%** |           |


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