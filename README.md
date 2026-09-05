# omsi-bus-extractor

## pack to exe
```sh
uv run pyinstaller --onefile --noconsole main.py
```

## Run tests
```sh
uv run pytest tests/ -v
```

## Todo
- [ ] auto detect file encoding
- [ ] add more logging when error (maybe add a log file)
- [ ] allow files that are out of the bus directory
- [ ] loading bar