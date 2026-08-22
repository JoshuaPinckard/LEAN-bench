import sys
sys.stdout.reconfigure(encoding="utf-8")
src = open("QuantCode-Bench/quantcode_bench/generator.py", encoding="utf-8").read()
i = src.find("SYSTEM_PROMPT_EN = ")
q = src.find('"""', i) + 3
j = src.find('"""', q)
prompt = src[q:j]
open("qcb_system_prompt.txt", "w", encoding="utf-8").write(prompt)
print("saved", len(prompt), "chars")
print(prompt[:1400])
print("......")
print(prompt[-600:])
