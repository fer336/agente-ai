from datetime import timedelta

#: How long a conversation stays parked in `mode="human"` after the LAST staff reply
#: before the next inbound patient message hands the chat back to the agent. The check
#: is lazy: nothing fires on a timer, it is only evaluated when a patient message
#: arrives while `mode="human"`. Every staff reply restarts the clock, and it never
#: expires when staff never replied (`conversation.last_human_reply_at is None`).
HUMAN_MODE_REACTIVATION_TIMEOUT = timedelta(hours=1)
