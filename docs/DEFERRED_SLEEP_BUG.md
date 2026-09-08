# Deferred Sleep behavior report

Player report after installing Re-Gear 0.3.53: pressing the Ally power button
does not sleep, and selecting Sleep from Steam's power menu also does not sleep.
The player suspects a possible relationship to the disconnect double-press flow,
but the trigger and cause are unconfirmed. Do not infer that relationship.

The player confirmed the Ally otherwise ready with working screen, audio and
controls, and explicitly requested that eGPU disconnect work remain the priority.
Record this for later investigation; do not change sleep handling during the
current supervised disconnect trial. Capture the precise topology, guard state,
pending transactions and reproduction steps when this issue is resumed.
