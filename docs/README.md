# Camera documentation

Maintain the module overview in the root `README.md` and operator/application
guides in each component's `README.md`, beside its source code. Maintain benchmark
reports in `operators/<name>/benchmarks.md`. The SDK documentation
build generates their MDX pages in an isolated build tree; do not commit or edit generated copies under `docs/`.

`fern/index.yml` lists the maintained source paths, explicit page titles, and
stable slugs for the Holoscan SDK guide under `modules/camera`. The Overview entry
points to `../../README.md`; the SDK generates `camera/overview.mdx` from it.
Component entries point to `../../operators/<name>/README.md` or
`../../applications/<name>/README.md`. Benchmark entries point to
`../../operators/<name>/benchmarks.md`; the SDK generates their MDX alongside the
operator and application pages. Group pages into Operators, Applications, and Benchmarks
using `section`, `slug`, `skip-slug: true`, and `contents`. The group labels organize
the sidebar without changing page URLs; keep page slugs unique across all groups.
Grouped navigation and root-README import require the corresponding SDK importer
support. The generated overview keeps the existing `overview` slug.

Use relative links between READMEs and other guides so they work when browsing
the repository. The SDK importer maps listed pages to their published routes,
copies local images, and points other source links to the public repository.
Complete `holoscan-module-internal` blocks are omitted before link processing,
matching the public source projection; malformed or unbalanced markers fail
assembly. SDK version-sync markers remain in the maintained README.
README titles are omitted from the generated MDX because Fern supplies the title
from navigation. HTML comments are omitted, prose braces are escaped, and `<br>`
tags are normalized; fenced examples and inline code are preserved. Keep other
markup MDX compatible and validate with Fern after changing it.

## Processing during SDK documentation generation

| Input | Processing during Camera documentation assembly | Result or limitation |
| --- | --- | --- |
| Root or operator/application `README.md` listed in `docs/fern/index.yml` | Generate MDX in the temporary SDK docs tree. | The README stays the maintained source; generated files are not committed. |
| Operator `benchmarks.md` listed in the fragment | Generate MDX using the same conversion as READMEs. | Reports stay beside their operators; existing benchmark slugs are preserved. |
| Relative link to `benchmarks.md` from its operator README | Map the listed report to its Fern route. | For SIPL, becomes `/holoscan/sdk-user-guide/modules/camera/sipl-benchmarks`. |
| Relative link to `../../Dockerfile` | Link to the public GitHub source file. | Source files absent from navigation stay on GitHub; authors can use repository-relative links. |
| Authored `.mdx` page listed in the fragment | Import it and process supported links. | Older authored-MDX overviews and benchmark reports remain supported. |
| Leading README H1 | Remove it; use the navigation title. | Other headings remain, and navigation slugs determine published routes. |
| Simple inline relative link to a listed guide, such as `../../operators/sipl_capture_op/README.md#tests` | Resolve it against the source file, then map it to the guide route. | Becomes `/holoscan/sdk-user-guide/modules/camera/sipl-capture#tests`; fragments are preserved. |
| Absolute URL, including `https://github.com/nvidia-holoscan/holoscan-camera/blob/main/README.md` | Leave it unchanged. | It still opens GitHub at `main`; selecting a Camera commit does not pin these URLs or convert them to Fern routes. |
| Relative link to another existing repository file or directory, when absent from navigation | Convert it to a public GitHub `blob/main` or `tree/main` URL. | Content absent from navigation is not imported automatically. A listed root README maps to the Overview route, including setup fragments. |
| Relative PNG, JPG, JPEG, GIF, SVG, WebP or PDF link | Copy the file from inside the checkout and rewrite its relative asset path. | Assets can live beside component READMEs or under `docs/`. |
| Same-page fragment or site-absolute path | Leave it unchanged. | Internal destinations are checked during combined-guide validation. |
| Marked `holoscan-module-internal` blocks in READMEs | Remove the entire block before normalizing prose or rewriting links. | Internal setup content is excluded; malformed or unbalanced markers fail assembly. |
| README HTML comments, prose braces and `<br>` tags | Omit comments, escape braces and make line-break tags self-closing. | This normalization applies to README prose, not authored MDX pages. |
| Fenced examples and inline code | Preserve them during conversion and link rewriting. | Example links and code are not rewritten or executed. |
| Reference-style links, HTML `href`/`src` and other markup | No dedicated link conversion. | Use supported inline Markdown for relative repository links; other markup must be MDX compatible. |
| Missing relative target, path escaping the checkout, unlisted `.mdx` target, or invalid/duplicate navigation entry | Fail assembly with an error. | Symlink targets must also stay inside the checkout. |
| External website availability | No remote URL reachability check. | Passing local link validation does not prove a GitHub page or external URL exists. |
| Archived SDK docs and source checkouts | Apply the module overlay only to the current guide's temporary tree. | Archives and maintained source files are unchanged. |

The repository README owns SDK setup and version-sync markers; update the SDK
baseline with `tools/sync_doc_versions.py`.

To validate from a public SDK checkout containing Camera documentation support:

```bash
python3 docs/scripts/build_holoscan_docs.py --skip-library-mdx \
  --camera-source-dir /path/to/holoscan-camera
```

The default build uses Docker to supply the documentation tools. This generates
the overview and component pages, validates links, and runs Fern. Both source
checkouts stay unchanged. Add `--preview` and open
`http://localhost:3000/holoscan/sdk-user-guide/modules/camera/overview`. Restart the
command after editing Camera sources: the assembled guide is a snapshot.
Publishing remains controlled by the SDK documentation workflow.
