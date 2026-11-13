"""Pin the large training sources (0.9.0): exact upstream revision, size and SHA-256 of every file.

Run: python scripts/pin-large-sources.py  (writes backend/moth/datafactory/large_sources.py)
"""
import json, urllib.request
def tree(repo, rev, path):
    url=f"https://huggingface.co/api/datasets/{repo}/tree/{rev}/{path}"
    return json.load(urllib.request.urlopen(url, timeout=60))
def files(repo, rev, dirs, pattern=lambda p: p.endswith(".parquet") and "/train-" in p or p.split("/")[-1].startswith("000_")):
    out=[]
    for d in dirs:
        for e in tree(repo, rev, d):
            if e["type"]=="file" and e.get("lfs") and pattern(e["path"]):
                out.append({"path": e["path"], "size": e["size"], "role": "train", "sha256": e["lfs"]["oid"]})
    return sorted(out, key=lambda f: f["path"])
COS=("HuggingFaceTB/cosmopedia","0ae6ec63f91742bd2d1eaef4f02232c55d719385")
SMOL=("HuggingFaceTB/smoltalk","5feaf2fd3ffca7c237fc38d1861bc30365d48ffa")
FW=("HuggingFaceFW/fineweb-edu","87f09149ef4734204d70ed1d046ddc9ca3f2b8f9")
cos=dict(license="Apache-2.0", license_url="https://www.apache.org/licenses/LICENSE-2.0",
         attribution="Cosmopedia by Hugging Face (Apache-2.0)", repo=COS[0], revision=COS[1], format="parquet_text")
smol=dict(license="Apache-2.0", license_url="https://www.apache.org/licenses/LICENSE-2.0",
          attribution="SmolTalk by Hugging Face (Apache-2.0; Smol-Magpie-Ultra, Smol-constraints, Smol-rewrite, Smol-summarize)",
          repo=SMOL[0], revision=SMOL[1], format="parquet_messages")
S=[
 {"id":"cosmopedia-stories","name":"Cosmopedia stories","domain":"language",**cos,
  "description":"Millions of synthetic short stories in clear English (Cosmopedia).","files":files(*COS,["data/stories"])},
 {"id":"cosmopedia-textbooks","name":"Cosmopedia textbooks","domain":"knowledge",**cos,
  "description":"Textbook-style lessons seeded from Khan Academy, OpenStax, Stanford courses and WikiHow.",
  "files":files(*COS,["data/khanacademy","data/openstax","data/wikihow","data/stanford"])},
 {"id":"cosmopedia-math","name":"Cosmopedia math texts","domain":"math",**cos,
  "description":"Step-by-step mathematics explanations (Cosmopedia auto_math_text).","files":files(*COS,["data/auto_math_text"])},
 {"id":"cosmopedia-web","name":"Cosmopedia web-seeded articles","domain":"knowledge",**cos,
  "description":"Educational articles on a very wide range of topics (Cosmopedia web_samples_v2).","files":files(*COS,["data/web_samples_v2"])},
 {"id":"fineweb-edu","name":"FineWeb-Edu (10B token sample)","domain":"knowledge","repo":FW[0],"revision":FW[1],
  "format":"parquet_text","license":"ODC-By-1.0","license_url":"https://opendatacommons.org/licenses/by/1-0/",
  "attribution":"FineWeb-Edu by Hugging Face (ODC-By 1.0); content from Common Crawl, subject to its terms of use",
  "description":"High-quality educational web pages filtered from Common Crawl.","files":files(*FW,["sample/10BT"],pattern=lambda p: p.endswith(".parquet"))},
 {"id":"smoltalk-magpie","name":"SmolTalk Magpie-Ultra conversations","domain":"conversation",**smol,
  "description":"Multi-turn assistant conversations (Smol-Magpie-Ultra).","files":files(*SMOL,["data/smol-magpie-ultra"])},
 {"id":"smoltalk-skills","name":"SmolTalk constraints, rewriting and summaries","domain":"writing",**smol,
  "description":"Following format constraints, rewriting text and summarising.",
  "files":files(*SMOL,["data/smol-constraints","data/smol-rewrite","data/smol-summarize"])},
 {"id":"metamathqa","name":"MetaMathQA","domain":"math","repo":"meta-math/MetaMathQA","revision":"aa4f34d3d2d3231299b5b03d9b3e5a20da45aa18",
  "format":"qa_json","fields":["query","response"],"license":"MIT","license_url":"https://opensource.org/licenses/MIT",
  "attribution":"MetaMathQA by Yu et al. (MIT)","description":"395,000 mathematics questions with worked solutions.",
  "files":[{"path":"MetaMathQA-395K.json","size":395626321,"role":"train","sha256":"fb39a5d8c05c042ece92eae37dfd5ea414a5979df2bf3ad3b86411bef8205725"}]},
 {"id":"oasst2","name":"OpenAssistant Conversations 2 (oasst2)","domain":"conversation","repo":"OpenAssistant/oasst2",
  "revision":"179dd21fc55192153d94adb0e0ce8f69e222bf75","format":"oasst_trees","license":"Apache-2.0",
  "license_url":"https://www.apache.org/licenses/LICENSE-2.0","attribution":"OpenAssistant Conversations 2 (oasst2) by LAION and contributors (Apache-2.0)",
  "description":"More multi-turn human conversations with an assistant, best-ranked replies only.",
  "files":[{"path":"2023-11-05_oasst2_ready.trees.jsonl.gz","size":54370156,"role":"train","sha256":"7a886a16ccfc1173c4f00a6897523e3c95b2785a86ee44a18a98f4f2807ee29b"}]},
 {"id":"tinystories-full","name":"TinyStories (full training set)","domain":"language","repo":"roneneldan/TinyStories",
  "revision":"f54c09fd23315a6f9c86f9dc80f725de7d8f9c64","format":"stories","license":"CDLA-Sharing-1.0",
  "license_url":"https://cdla.dev/sharing-1-0/","attribution":"TinyStories by Ronen Eldan and Yuanzhi Li (Microsoft Research)",
  "description":"The full 2.7 million story training set.",
  "files":[{"path":"TinyStoriesV2-GPT4-train.txt","size":2227753162,"role":"train","sha256":"6418d412de72888f52b5142c761ac21a582f7d1166f0bfbdb5f03ccfdec90443"}]},
]
OC2=("OpenCoder-LLM/opc-sft-stage2","7d28f40d579edd7c24402d17d0c7639f991e6f8d")
OC1=("OpenCoder-LLM/opc-sft-stage1","1bcab575f5e2d1c1fd6652720418524c27b3d58b")
oc=dict(format="parquet_qa",fields=["instruction","output"],license="MIT",license_url="https://opensource.org/licenses/MIT",
        attribution="OpenCoder SFT data by the OpenCoder team (MIT)")
S += [
 {"id":"opencoder-sft","name":"OpenCoder code instructions (stage 2)","domain":"code","repo":OC2[0],"revision":OC2[1],**oc,
  "description":"Educational, evolved and package-usage coding tasks with solutions; educational tasks were validated by executing tests.",
  "files":files(*OC2,["educational_instruct","evol_instruct","package_instruct","mceval_instruct"],pattern=lambda p:p.endswith(".parquet"))},
 {"id":"opencoder-diverse","name":"OpenCoder large-scale diverse code instructions","domain":"code","repo":OC1[0],"revision":OC1[1],**oc,
  "description":"Millions of diverse programming questions with answers.",
  "files":files(*OC1,["data"],pattern=lambda p:"largescale_diverse_instruct" in p)},
 {"id":"smoltalk-code","name":"SmolTalk self-instructed code","domain":"code",**smol,
  "license":"ODC-By-1.0","license_url":"https://opendatacommons.org/licenses/by/1-0/",
  "attribution":"StarCoder2 Self-OSS-Instruct via SmolTalk, BigCode / Hugging Face (ODC-By 1.0)",
  "description":"Python coding tasks with solutions, filtered by executing them.","files":files(*SMOL,["data/self-oss-instruct"])},
]
for s in S:
    s["sharded"]=len(s["files"])>1
    print(s["id"], len(s["files"]), round(sum(f["size"] for f in s["files"])/1e9,2),"GB")
import pathlib, pprint
dest = pathlib.Path(__file__).resolve().parents[1] / "backend/moth/datafactory/large_sources.py"
dest.write_text('"""Large training sources (0.9.0), pinned by scripts/pin-large-sources.py: exact upstream revision,\n'
                'size and SHA-256 of every file. Sharded sources are downloaded one file at a time as the library grows."""\n\n'
                "SOURCES = " + pprint.pformat(S, width=120, sort_dicts=False) + "\n")
