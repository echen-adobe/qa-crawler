import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Mapping

from bs4 import BeautifulSoup

from .logger import Logger
from qa_crawler.config import (
    BLOCK_MAP_OUTPUT_DIR,
    DEFAULT_BLOCK_MAP,
    DOM_SNAPSHOT_DIR,
    SOURCE_FILES_PATH,
    ensure_data_directories,
)


class SourceLogger(Logger):
    def __init__(self, *, new_version: bool = False, url_to_sitemap: Mapping[str, str] | None = None):
        super().__init__()
        self.source_dict: dict[str, list[str]] = {}
        self.new_version = new_version
        self.url_to_sitemap = dict(url_to_sitemap or {})
        self.manual_fallback_label = "manual entries"
        self.legacy_block_map: dict[str, dict[str, Any]] = {}
        self.grouped_block_maps: dict[str, dict[str, Any]] = {}
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="snapshot_writer")
        self.pending_snapshots = set()  # Track URLs with pending snapshots
        ensure_data_directories()

    async def init_on_page(self, page, url):
        self.source_dict[url] = []
        self.page = page
        self.pending_requests = 0
        page.on(
            "response",
            lambda response: self._filter_source_files(response.request.url, self.source_dict[url]),
        )

    async def log(self, page, url, environment):
        html_content = await page.content()
        self.pending_snapshots.add(url)
        self.executor.submit(self._write_snapshot_threaded, url, html_content)

    def _write_snapshot_threaded(self, url, html_content):
        try:
            safe_name = url.replace("://", "_").replace("/", "_") + ".html"
            output_path = DOM_SNAPSHOT_DIR / safe_name
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(html_content, encoding="utf-8")
            print(f"DOM snapshot saved to {output_path}")
        except Exception as e:
            print(f"Error writing snapshot for {url}: {e}")
        finally:
            self.pending_snapshots.discard(url)

    def write_logs(self):
        print("Waiting for snapshot writing to complete...")
        self.executor.shutdown(wait=True)
        print("Processing snapshots...")
        for url in self.source_dict.keys():
            self.query_dom_snapshot(url)

        existing_source_files = {}
        try:
            existing_source_files = json.loads(SOURCE_FILES_PATH.read_text(encoding="utf-8"))
        except FileNotFoundError:
            pass

        for url, sources in self.source_dict.items():
            if url in existing_source_files:
                existing_source_files[url] = list(set(existing_source_files[url] + sources))
            else:
                existing_source_files[url] = sources

        SOURCE_FILES_PATH.parent.mkdir(parents=True, exist_ok=True)
        SOURCE_FILES_PATH.write_text(json.dumps(existing_source_files, indent=2), encoding="utf-8")
        print(f"Source files saved to {SOURCE_FILES_PATH} (merged {len(self.source_dict)} new entries)")

        if self.new_version:
            self._write_new_block_map_outputs()
            return

        existing_block_map: dict[str, dict[str, Any]] = {}
        try:
            existing_block_map = json.loads(DEFAULT_BLOCK_MAP.read_text(encoding="utf-8"))
        except FileNotFoundError:
            pass

        for hash_key, hash_data in self.legacy_block_map.items():
            if hash_key in existing_block_map:
                existing_urls = set(existing_block_map[hash_key].get("urls", []))
                new_urls = set(hash_data.get("urls", []))
                existing_block_map[hash_key]["urls"] = list(existing_urls | new_urls)
                existing_block_map[hash_key]["class_names"] = hash_data.get("class_names", [])
            else:
                existing_block_map[hash_key] = hash_data

        DEFAULT_BLOCK_MAP.parent.mkdir(parents=True, exist_ok=True)
        DEFAULT_BLOCK_MAP.write_text(json.dumps(existing_block_map, indent=2), encoding="utf-8")
        print(f"Block map saved to {DEFAULT_BLOCK_MAP} (merged {len(self.legacy_block_map)} new entries)")

    def _filter_source_files(self, response_url, source_files):
        block_path = "/express/code/blocks/"
        if response_url.endswith(".js") and block_path in response_url:
            source_files.append(response_url)

    async def query_variants(self, block_name):
        output = []
        variants = await self.page.query_selector_all(f"main .{block_name}")
        if variants:
            for variant in variants:
                class_attr = await variant.get_attribute("class")
                output.append(class_attr.split() if class_attr else [])
            return output
        else:
            return None

    def hash_variants(self, variants):
        if not variants:
            return None
        hash_map = {}
        for variant_array in variants:
            variant_str = " ".join(sorted(variant_array))
            variant_hash = hashlib.sha256(variant_str.encode()).hexdigest()
            hash_map[variant_hash] = variant_array
        return hash_map

    def query_dom_snapshot(self, url):
        snapshot_path = DOM_SNAPSHOT_DIR / f"{url.replace('://', '_').replace('/', '_')}.html"
        try:
            html_content = snapshot_path.read_text(encoding="utf-8")
            soup = BeautifulSoup(html_content, "html.parser")
            main_element = soup.find("main")
            if not main_element:
                print(f"No main element found in {snapshot_path}")
                return
            section_elements = main_element.find_all(class_="section", recursive=True)
            block_store = self._get_block_store(url)
            for section in section_elements:
                direct_children = section.find_all(recursive=False)
                for element in direct_children:
                    def add_block_entry(classes: list[str]):
                        if not classes:
                            return
                        sorted_class_names = sorted(classes)
                        class_str = " ".join(sorted_class_names)
                        element_hash = hashlib.sha256(class_str.encode()).hexdigest()
                        if element_hash not in block_store:
                            block_store[element_hash] = {
                                "class_names": classes,
                                "urls": [],
                            }
                        if url not in block_store[element_hash]["urls"]:
                            block_store[element_hash]["urls"].append(url)

                    class_names = element.get("class", [])
                    if class_names:
                        add_block_entry(class_names)
                        if any(cls.endswith("-wrapper") for cls in class_names):
                            child_divs = element.find_all("div", recursive=False)
                            for child in child_divs:
                                child_classes = child.get("class", [])
                                add_block_entry(child_classes)

        except FileNotFoundError:
            print(f"Snapshot file not found: {snapshot_path}")
        except Exception as e:
            print(f"Error processing snapshot {snapshot_path}: {e}")

    def cleanup(self):
        if hasattr(self, "executor") and self.executor:
            self.executor.shutdown(wait=True)
            print("SourceLogger thread executor shutdown complete")

    def _get_block_store(self, url: str) -> dict[str, dict[str, Any]]:
        if not self.new_version:
            return self.legacy_block_map
        label = self.url_to_sitemap.get(url) or self.manual_fallback_label
        return self.grouped_block_maps.setdefault(label, {})

    def _write_new_block_map_outputs(self) -> None:
        BLOCK_MAP_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        index_entries: dict[str, str] = {}

        for label, block_map in self.grouped_block_maps.items():
            if not block_map:
                continue
            hashcode = hashlib.sha256(label.encode("utf-8")).hexdigest()[:12]
            filename = f"block-map-{hashcode}.json"
            file_path = BLOCK_MAP_OUTPUT_DIR / filename
            try:
                file_path.write_text(json.dumps(block_map, indent=2), encoding="utf-8")
                index_entries[filename] = label
                print(f"Block map saved to {file_path} (source: {label})")
            except Exception as exc:
                print(f"Failed to write block map for {label}: {exc}")

        index_path = BLOCK_MAP_OUTPUT_DIR / "index.json"
        combined_index: dict[str, str] = {}
        try:
            existing_text = index_path.read_text(encoding="utf-8")
            combined_index = json.loads(existing_text) if existing_text else {}
        except FileNotFoundError:
            combined_index = {}
        except json.JSONDecodeError:
            print(f"Existing index at {index_path} is malformed; regenerating.")
            combined_index = {}

        combined_index.update(index_entries)

        try:
            index_path.write_text(json.dumps(combined_index, indent=2), encoding="utf-8")
            print(f"Block map index saved to {index_path}")
        except Exception as exc:
            print(f"Failed to write block map index: {exc}")
