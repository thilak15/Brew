# Brew Demo Script

Traditional drive-thru ordering breaks down in three places: speed, accuracy, and consistency.
At rush hour, lines grow because one human operator can only process one car at a time.
On noisy speakers, customers repeat themselves, modifiers get missed, and incorrect orders cost time, money, and trust.
Staffing shortages make this worse.
The core problem is simple: the ordering interface has not evolved.

I built Brew to solve that.
Brew is a real-time, voice-first AI drive-thru barista that replaces the speaker-box operator with a live conversational agent.
Customers order exactly the way they naturally speak.
No tapping, no typing, no scripted menu trees.
Just conversation.

Brew runs end-to-end on Google AI and Google Cloud:
Gemini Live API for native audio interaction,
Google ADK for tool orchestration,
Cloud Run for deployment,
and Firestore for persistent session and cart state.

Let me show it live.

In production, session start would be triggered by vehicle detection near the speaker.
For this demo, I click Drive Up.
The agent greets immediately and starts listening.

Now I place a normal drink order:
"Can I get a grande iced latte?"

The agent confirms, and the receipt updates immediately with item, size, and price.
No manual submit step.

Next I modify that drink naturally:
"Add oat milk and vanilla syrup to that."

Brew applies both modifiers to the existing item and updates the receipt in real time.

Now a multi-item request in one sentence:
"Also, I’ll take a spinach feta wrap and a cake pop."

Brew handles this as a batch action, adds both items, and updates the UI instantly.
The menu view also shifts context automatically to the relevant category.

Now I demonstrate interruption handling, which is critical in real drive-thru flow.
I interrupt the agent mid-response:
"Actually, make that latte with extra ice."

Brew stops speaking immediately, listens, and applies the change.
This barge-in behavior is what makes the experience truly live instead of turn-based.

Now a correction:
"Remove the cake pop."

Brew removes the item and recalculates total immediately.

Then I finish:
"That’s everything."

Brew gives a clean order summary with total and completion prompt.

What you just saw is not a scripted happy path.
It is a live voice agent handling real ordering behavior:
additions, modifiers, batch requests, interruptions, corrections, and closeout.

Under the hood, the browser captures microphone audio with AudioWorklet and streams PCM over WebSocket.
The FastAPI backend on Cloud Run maintains a bidirectional live session with Gemini through ADK.
When the model decides to take an action, it calls one of Brew’s order tools.
Those tool calls update shared order state and sync to Firestore so state survives instance restarts and scaling.

Brew includes 14 order-management tools, including batch operations for lower latency and better conversational flow.
It also includes reliability controls for production behavior:
a tool-gate to prevent feedback loops during tool execution,
idempotency guards to block duplicate modifications,
and proactive reconnect before the Gemini Live session limit, with order-context injection so the conversation continues seamlessly.

Brew also mirrors customer language in real time, enabling multilingual ordering without separate language-mode setup.

The bigger point is this:
Brew is menu-driven and menu-agnostic.
The same architecture can power coffee, quick-service restaurants, pharmacy pickup, or any voice ordering workflow.

Drive-thru has stayed mostly unchanged for decades.
Brew shows what the next interface looks like:
not chat,
not button-heavy UI,
but a real-time conversational agent that listens, reasons, acts, and responds live.

This is Brew.
