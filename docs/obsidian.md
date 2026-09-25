# Obsidian tips

You don't need Obsidian to use Notes Vault. These are for when you want the notes on your computer or phone. Syncing is covered in the [README](../README.md#obsidian); any WebDAV client works too (Finder's **Connect to Server**, rclone, Cyberduck), so an app without its own sync can open a mounted or synced copy.

## Names instead of entity IDs

Obsidian shows the file name as a note's title, so an entity note shows up as `light.kitchen_ceiling`. [Front Matter Title](https://github.com/snezhig/obsidian-front-matter-title) shows a frontmatter key instead, without renaming the file.

1. Set **Common main template** to `name`, the key Notes Vault writes the friendly name to.
2. Turn on the features you want. Each one is off until you enable it:

| Feature | What it changes |
| --- | --- |
| **Explorer** (and **Explorer → Sort**) | File explorer shows and sorts by `Ceiling lamp` |
| **Search** | Search results |
| **Suggest** | Quick switcher and `[[` link suggestions |
| **Bookmarks** | Bookmarked notes |
| **Backlink** | The backlinks pane, where a device note lists the entities pointing at it |
| **Tabs**, **Header**, **Inline**, **Window Frame Title** | Tab, header, inline and window titles |
| **Graph** | Graph view nodes |
| **Canvas** | Cards on a canvas |
| **Note Link** | Rewrites the text of `[[light.kitchen_ceiling]]` to the name. Use **Replace only links without alias**. It edits your files, so every rewrite is a change to sync. |

Leave **Alias** off: the notes already carry their name in `aliases`. Links work either way: type `[[Ceiling`, pick the alias, and Obsidian inserts `[[light.kitchen_ceiling|Ceiling lamp]]`.

## A cleaner graph

The templates aren't about anything in your home, so they float on their own. Hide them with `-path:"Home Assistant/Templates"` in the graph filter, and add `-path:"Home Assistant/Index"` so the index doesn't pull every note you've written into one cluster.

## Dataview

[Dataview](https://github.com/blacksmithgu/obsidian-dataview) turns the frontmatter into queries. Every light that links to the kitchen:

````markdown
```dataview
TABLE name, device FROM #Home-Assistant/Entity/Light AND [[Kitchen]]
```
````

Tags under `Home-Assistant/` are generated and named after the integration (`Home-Assistant/Entity/Air-Quality`, `Home-Assistant/Device/Philips-Hue`), so the tag pane reads as a tree of your home. Tags you add yourself are kept.

## Obsidian-side MCP servers

MCP servers such as [mcp-obsidian](https://github.com/MarkusPfundstein/mcp-obsidian) talk to Obsidian through the [Local REST API](https://github.com/coddingtonbear/obsidian-local-rest-api) plugin, so an assistant on your computer can work on the synced copy. You don't need it for an assistant that already talks to Home Assistant.
