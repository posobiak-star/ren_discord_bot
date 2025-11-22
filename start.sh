#!/bin/bash
# web(Flask) をバックグラウンドで起動
python web.py &

# Discord Bot を起動
python bot.py
