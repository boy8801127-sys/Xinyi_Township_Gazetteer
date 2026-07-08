# -*- coding: utf-8 -*-
import os, sys
from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv()
client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

batch_id = sys.argv[1] if len(sys.argv) > 1 else "msgbatch_01MNny3Wu3rUkdrm5gha8evV"
batch = client.messages.batches.retrieve(batch_id)
c = batch.request_counts
print(f"Batch: {batch_id}")
print(f"成功: {c.succeeded}, 失敗: {c.errored}")

total_input = 0
total_output = 0
for result in client.messages.batches.results(batch_id):
    if result.result.type == "succeeded":
        usage = result.result.message.usage
        total_input  += usage.input_tokens
        total_output += usage.output_tokens

print(f"Input tokens : {total_input:,}")
print(f"Output tokens: {total_output:,}")

# claude-haiku-4-5 Batch API 價格（正常價 50% off）
# Input  $1.00/1M → Batch $0.50/1M
# Output $5.00/1M → Batch $2.50/1M
input_cost  = total_input  / 1_000_000 * 0.50
output_cost = total_output / 1_000_000 * 2.50
total_usd   = input_cost + output_cost
print(f"Input  費用: ${input_cost:.5f}")
print(f"Output 費用: ${output_cost:.5f}")
print(f"合計:        ${total_usd:.5f} USD")
print(f"約台幣:      NT${total_usd * 32:.2f}")
