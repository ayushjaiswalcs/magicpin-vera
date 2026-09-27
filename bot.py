"""Vera Context: deterministic challenge bot. Python 3.11+, no dependencies.
Run `python3 bot.py`. HTTP transport is for challenge use behind a TLS proxy.
No outbound network calls, model keys, real WhatsApp sends or business mutations.
"""
from __future__ import annotations
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
VERSION = "1.0.0"
SCOPES = ("category", "merchant", "customer", "trigger")
ID_FIELDS = dict(category="slug", merchant="merchant_id", customer="customer_id", trigger="id")
TEMPLATE = "{{1}}, {{2}} {{3}}"
CONSENT = {
    "recall_due": {"recall_reminders"}, "customer_lapsed_soft": {"recall_reminders", "winback_offers"},
    "customer_lapsed_hard": {"winback_offers"}, "appointment_tomorrow": {"appointment_reminders"},
    "chronic_refill_due": {"refill_reminders"}, "trial_followup": {"trial_followup", "program_updates", "kids_program_updates"},
    "wedding_package_followup": {"bridal_package_followup"},
    "renewal_due": {"renewal_reminders"}, "festival_upcoming": {"promotional_offers"},
}
ALIASES = {"category_research_digest_release": "research_digest", "research_digest_release": "research_digest",
           "scheduled_recurring": "curious_ask_due", "category_trend_movement": "trend"}

def stamp(value):
    if not isinstance(value, str):
        raise ValueError("Timestamp must be an ISO-8601 string")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)

def iso_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def readable(value):
    return str(value).replace("_", " ")

def pct(value):
    return f"{float(value) * 100:g}%"

def kind_of(trigger):
    return ALIASES.get(trigger.get("kind"), trigger.get("kind", ""))

def refs(trigger):
    p = trigger.get("payload", {})
    return trigger.get("merchant_id") or p.get("merchant_id"), trigger.get("customer_id") or p.get("customer_id")

def hindi(merchant, customer=None, message=""):
    if message:
        if re.search(r"[\u0900-\u097f]|\b(haan|han|nahi|mujhe|karo|chahiye|bhejo|kaise|kya|hai)\b", message.lower()):
            return True
        if re.search(r"\b(please|yes|send|want|how|what|hello|thanks)\b", message.lower()):
            return False
    if customer:
        return "hi" in customer.get("identity", {}).get("language_pref", "").lower()
    identity = merchant.get("identity", {})
    pref = identity.get("language_pref")
    return ("hi" in pref.lower()) if pref else "hi" in identity.get("languages", [])

def active_offer(merchant):
    return next((o["title"] for o in merchant.get("offers", []) if o.get("status") == "active" and o.get("title")), None)

def digest_item(category, trigger):
    p = trigger.get("payload", {})
    if isinstance(p.get("top_item"), dict):
        return p["top_item"]
    item_id = p.get("top_item_id") or p.get("digest_item_id") or p.get("alert_id")
    items = category.get("digest", [])
    if item_id:
        return next((i for i in items if i.get("id") == item_id), None)
    wanted = {"regulation_change": "compliance", "cde_opportunity": "cde", "trend": "trend"}.get(kind_of(trigger), "research")
    return next((i for i in reversed(items) if i.get("kind") == wanted), None)

def consent_reason(customer, merchant, trigger):
    if not customer or customer.get("merchant_id") != merchant.get("merchant_id"):
        return "Customer missing or belongs to another merchant"
    consent = customer.get("consent", {})
    pref = customer.get("preferences", {})
    if consent.get("revoked_at") or consent.get("opted_out") or pref.get("reminder_opt_in") is False:
        return "Customer has withdrawn consent"
    if pref.get("channel", "whatsapp") != "whatsapp":
        return "Customer channel is not WhatsApp"
    allowed = CONSENT.get(kind_of(trigger), set())
    scopes = consent.get("scope", [])
    if not consent.get("opted_in_at") or not allowed.intersection(scopes):
        return "No matching opt-in scope for this trigger"
    if kind_of(trigger) == "chronic_refill_due" and merchant.get("category_slug") != "pharmacies":
        return "Refill trigger incompatible with merchant category"
    return None

def slots_for(trigger):
    p = trigger.get("payload", {})
    rows = p.get("available_slots") or p.get("next_session_options") or []
    result = []
    for row in rows[:3]:
        # Use ISO, not inconsistent weekday labels supplied in the sample data.
        if isinstance(row, dict) and row.get("iso"):
            try:
                dt = datetime.fromisoformat(row["iso"].replace("Z", "+00:00"))
                result.append(dt.strftime("%a %d %b, %I:%M %p") + " " + dt.strftime("%z"))
            except ValueError:
                continue
        elif isinstance(row, dict) and row.get("label"):
            result.append(row["label"])
    return result

def compose(category: dict, merchant: dict, trigger: dict, customer: dict | None = None) -> dict:
    """Pure, deterministic four-context composition. Never mutates inputs.
    Suppressed compositions return an empty body and a reason; tick never sends them.
    """
    kind = kind_of(trigger)
    p = trigger.get("payload", {})
    identity = merchant.get("identity", {})
    name = identity.get("name", "your business")
    hi = hindi(merchant, customer)
    send_as = "merchant_on_behalf" if trigger.get("scope") == "customer" else "vera"
    base = {"body": "", "cta": "none", "send_as": send_as,
            "suppression_key": trigger.get("suppression_key") or trigger.get("id", ""), "rationale": ""}
    def finish(greeting, fact, ask, cta="binary_yes_no", reason="Grounded in supplied context"):
        params = [greeting, fact.strip(), ask.strip()]
        base.update(body=TEMPLATE.replace("{{1}}", params[0]).replace("{{2}}", params[1]).replace("{{3}}", params[2]).strip(),
                    cta=cta, rationale=reason, template_name="merchant_context_v1" if send_as == "merchant_on_behalf" else "vera_context_v1",
                    template_params=params)
        return base
    def suppress(reason):
        base.update(suppressed=True, rationale=reason)
        return base
    yes = "YES bolein; messages band karne ke liye STOP." if hi else "Reply YES; STOP to opt out."
    greeting = identity.get("owner_first_name") or name
    if category.get("slug") == "dentists" and identity.get("owner_first_name"):
        greeting = "Dr. " + identity["owner_first_name"]
    offer = active_offer(merchant)
    perf = merchant.get("performance", {})
    window = perf.get("window_days", 30)
    anchor = f"{name}: "
    if send_as == "merchant_on_behalf":
        reason = consent_reason(customer, merchant, trigger)
        if reason:
            return suppress(reason)
        greeting = "Hi " + customer.get("identity", {}).get("name", "there")
        source = f"{name} se reminder." if hi else f"A reminder from {name}."
        if kind in ("recall_due", "customer_lapsed_soft"):
            service = readable(p.get("service_due", "follow-up"))
            fact = f"{source} {service}"
            fact += f" due: {p['due_date']}." if p.get("due_date") else ": would you like to plan your next visit?"
        elif kind == "appointment_tomorrow":
            when = p.get("appointment_time") or p.get("appointment_at") or p.get("appointment_iso")
            if not when:
                return suppress("Appointment time missing; do not invent a booking")
            fact = f"{source} Your appointment is scheduled for {when}."
        elif kind == "chronic_refill_due":
            if not p.get("stock_runs_out_iso"):
                return suppress("Refill date missing; cannot infer medicine supply")
            fact = f"{source} Your refill reminder is due {p['stock_runs_out_iso'][:10]}. The pharmacist must confirm prescription and stock; no medicine changes are suggested."
        elif kind == "wedding_package_followup":
            if not p.get("wedding_date"):
                return suppress("Wedding date missing")
            fact = f"{source} Following your bridal trial, your wedding date on file is {p['wedding_date']}."
        elif kind == "trial_followup":
            if not p.get("trial_date"):
                return suppress("Trial date missing")
            fact = f"{source} Following up on your trial on {p['trial_date']}."
        elif kind == "customer_lapsed_hard":
            fact = f"{source} Ready to return at your own pace?"
            if p.get("days_since_last_visit"):
                fact += f" It has been {p['days_since_last_visit']} days since your last visit."
        elif kind == "renewal_due":
            if "days_remaining" not in p:
                return suppress("Customer renewal timing missing")
            fact = f"{source} Your renewal is due in {p['days_remaining']} days."
        else:
            return suppress("No supported customer message for this trigger")
        slots = slots_for(trigger)
        if slots:
            fact += " Listed options: " + "; ".join(slots) + ". Availability needs reconfirmation."
        preferred = customer.get("preferences", {}).get("preferred_slots")
        if preferred and not slots:
            fact += f" Your preference on file: {readable(preferred)}."
        ask = ("Agla step coordinate karna hai? " if hi else "Would you like help with the next step? ") + yes
        return finish(greeting, fact, ask, reason=f"Customer {kind}; matching consent checked; dates and preferences from context; no booking or delivery claim")
    if kind in ("research_digest", "regulation_change", "cde_opportunity", "trend"):
        item = digest_item(category, trigger)
        if not item or not item.get("source") or not item.get("title"):
            return suppress("Referenced digest item or source missing")
        fact = f"{name} — supplied digest: {item['title']}. Source: {item['source']}."
        if item.get("summary"):
            fact += " " + item["summary"]
        if p.get("deadline_iso"):
            fact += f" Listed deadline: {p['deadline_iso']}."
        if item.get("date"):
            fact += f" Listed date: {item['date']}."
        ask = ("Iska review draft banaun? " if hi else "Shall I prepare a review draft from this item? ") + yes
        return finish(greeting, fact, ask, reason=f"{kind}; exact source-linked item; synthetic supplied claims are attributed, not externally verified")
    if kind in ("perf_dip", "perf_spike", "seasonal_perf_dip"):
        metric = p.get("metric")
        delta = p.get("delta_pct")
        if not metric or delta is None:
            wanted_sign = -1 if "dip" in kind else 1
            pair = next(((k[:-4], v) for k, v in perf.get("delta_7d", {}).items()
                         if k.endswith("_pct") and isinstance(v, (int, float)) and v * wanted_sign > 0), None)
            if not pair:
                return suppress("No supporting performance change in latest context")
            metric, delta = pair
        fact = f"{anchor}{readable(metric)} {'down' if delta < 0 else 'up'} {pct(abs(delta))} over {p.get('window', '7d')}."
        if metric in perf:
            fact += f" Latest {window}-day {readable(metric)}: {perf[metric]}."
        if "ctr" in perf and "avg_ctr" in category.get("peer_stats", {}):
            fact += f" CTR {pct(perf['ctr'])}; category benchmark {pct(category['peer_stats']['avg_ctr'])} ({category['peer_stats'].get('scope', 'provided peer group')})."
        if p.get("is_expected_seasonal"):
            fact += " The trigger flags a seasonal pattern; this does not establish the cause."
        ask = ("Ek focused action plan banaun? " if hi else "Shall I prepare one focused action plan? ") + yes
    elif kind == "renewal_due":
        sub = merchant.get("subscription", {})
        days = sub.get("days_remaining", p.get("days_remaining"))
        if days is None:
            return suppress("No renewal timing in context")
        fact = f"{anchor}{sub.get('plan', p.get('plan', 'current'))} plan has {days} days remaining."
        if "renewal_amount" in p:
            fact += f" Listed renewal amount: ₹{p['renewal_amount']:,}."
        ask = ("Renewal checklist chahiye? " if hi else "Want the renewal checklist? ") + yes
    elif kind in ("festival_upcoming", "ipl_match_today", "local_news_event", "weather_heatwave"):
        event = p.get("festival") or p.get("match") or p.get("headline") or p.get("event")
        if kind == "weather_heatwave":
            event = f"Heatwave: {p['temperature_c']}°C" if "temperature_c" in p else p.get("headline")
        if not event:
            return suppress("Event facts missing")
        fact = f"{anchor}{event}"
        date = p.get("date") or p.get("match_time_iso")
        fact += f" — {date}." if date else "."
        if kind == "ipl_match_today":
            fact += " Draft a match-night post only after confirming opening hours and offer eligibility."
        elif offer:
            fact += f" Your active offer is {offer}; confirm event-day terms before using it."
        ask = ("Review ke liye post draft banaun? " if hi else "Shall I draft a post for review? ") + yes
    elif kind == "review_theme_emerged":
        theme = p if p.get("theme") else next((r for r in merchant.get("review_themes", []) if r.get("sentiment") == "neg"), {})
        if not theme.get("theme"):
            return suppress("No review theme supplied")
        fact = f"{anchor}{readable(theme['theme'])} appears in {theme.get('occurrences_30d', 'the supplied')} reviews in the last 30 days."
        if theme.get("common_quote"):
            fact += f" Example: “{theme['common_quote']}”."
        ask = ("Customer reply aur internal checklist draft karun? " if hi else "Shall I draft a response and an internal checklist? ") + yes
    elif kind == "milestone_reached":
        if "value_now" not in p or "milestone_value" not in p:
            return suppress("Milestone counts missing; do not fabricate achievement")
        fact = f"{anchor}{readable(p.get('metric', 'count'))}: {p['value_now']}; milestone: {p['milestone_value']}."
        fact += " The milestone has not been reached yet." if p["value_now"] < p["milestone_value"] else " The milestone has been reached."
        ask = ("Neutral review-request draft chahiye? " if hi else "Want a neutral review-request draft, with no rewards or rating pressure? ") + yes
    elif kind == "competitor_opened":
        if not p.get("competitor_name"):
            return suppress("Competitor identity missing")
        fact = f"{anchor}the trigger lists {p['competitor_name']}"
        fact += f" {p['distance_km']} km away." if "distance_km" in p else "."
        if p.get("their_offer"):
            fact += f" Their listed offer: {p['their_offer']}."
        if offer:
            fact += f" Your active offer: {offer}."
        ask = ("Price cut ke bina positioning draft karun? " if hi else "Want a positioning draft without automatically cutting your price? ") + yes
    elif kind in ("curious_ask_due", "dormant_with_vera", "winback_eligible"):
        fact = f"{name} in {identity.get('locality', identity.get('city', 'your area'))}"
        if "calls" in perf:
            fact += f" — {perf['calls']} calls in the latest {window} days."
        else:
            fact += "."
        if kind == "winback_eligible":
            days = merchant.get("subscription", {}).get("days_since_expiry", p.get("days_since_expiry"))
            if days is not None:
                fact += f" Subscription expired {days} days ago; I won't assume that caused the change."
        if kind == "curious_ask_due":
            ask = "Is hafte customers sabse zyada kis service ke liye pooch rahe hain?" if hi else "Which service are customers asking about most this week?"
            return finish(greeting, fact, ask, "open_ended", "Weekly curiosity prompt anchored to this business; one question")
        ask = ("Ek chhota recovery plan banaun? " if hi else "Shall I draft a small recovery plan? ") + yes
    elif kind == "active_planning_intent":
        topic = readable(p.get("intent_topic", "your requested plan"))
        fact = f"{anchor}draft for {topic}: define the audience, service inclusions, capacity and delivery schedule."
        fact += f" Existing active offer: {offer}. Keep its terms unchanged until you approve a new package." if offer else "Price and availability need your confirmation."
        ask = "Kitni capacity rakhni hai?" if hi else "What capacity should this plan use?"
        return finish(greeting, fact, ask, "open_ended", "Explicit planning intent: provide an immediate draft instead of requalifying")
    elif kind == "gbp_unverified":
        if identity.get("verified") is True:
            return suppress("Latest merchant context says profile is verified; stale trigger")
        fact = f"{anchor}your Google Business Profile is marked unverified."
        if p.get("verification_path"):
            fact += " Supplied verification route: " + readable(p["verification_path"]) + "."
        ask = ("Verification checklist chahiye? " if hi else "Want a verification checklist? ") + yes
    elif kind == "supply_alert":
        item = digest_item(category, trigger)
        if not p.get("affected_batches") or not p.get("molecule"):
            return suppress("Supply alert lacks batch or product identification")
        fact = f"{anchor}supplied stock alert for {p['molecule']}, batches {', '.join(p['affected_batches'])}."
        if p.get("manufacturer"):
            fact += f" Manufacturer: {p['manufacturer']}."
        if item and item.get("source"):
            fact += f" Supplied source: {item['source']}."
        fact += " Ask the pharmacist to verify the official notice and match inventory before acting."
        return finish(greeting, fact, "", "none", "Time-sensitive stock alert; identified batches only; no patient treatment advice")
    elif kind == "category_seasonal":
        if not p.get("trends"):
            return suppress("Seasonal evidence missing")
        fact = f"{anchor}supplied {readable(p.get('season', 'seasonal'))} signals: {'; '.join(map(readable, p['trends']))}. These are category signals, not your sales."
        ask = ("Stock-review checklist banaun? " if hi else "Shall I draft a stock-review checklist? ") + yes
    else:
        return suppress("Unknown trigger kind; wait for actionable structured context")
    return finish(greeting, fact, ask, reason=f"{kind}; facts from trigger and latest merchant/category context; one primary CTA; no external action claimed")


def respond(state: dict, merchant_message: str) -> dict:
    """Pure reply planner. API persists status, opt-outs, delays and turn idempotency."""
    text = merchant_message.strip()
    lower = text.lower().replace("’", "'")
    merchant, category, trigger = state["merchant"], state["category"], state["trigger"]
    customer = state.get("customer")
    hi = hindi(merchant, customer, text)
    previous = state.get("received", [])
    def send(body, why, cta="none"):
        if body in state.get("sent", []):
            return {"action": "end", "rationale": "Already answered this request; avoid repeating the same message"}
        return {"action": "send", "body": body, "cta": cta, "rationale": why}
    if re.search(r"\b(stop|unsubscribe|opt out|don't message|do not contact|band karo|mat bhejo)\b|बंद करो", lower):
        return {"action": "end", "rationale": "Explicit opt-out: suppress future outreach for this recipient", "opt_out": True}
    if re.search(r"\b(not interested|no thanks|nahi chahiye|leave me alone)\b", lower) or lower in {"no", "nahi", "cancel"}:
        return {"action": "end", "rationale": "Declined: end conversation and cool down recipient", "cooldown_seconds": 30 * 86400}
    if re.search(r"thank you for (contacting|reaching)|automated (reply|assistant)|auto.?reply|our team will (respond|reply)|currently (away|unavailable)", lower) or previous.count(lower) >= 2:
        if state.get("auto_replies", 0) >= 1:
            return {"action": "end", "rationale": "Repeated automatic reply; end without another outbound", "auto_reply": True, "cooldown_seconds": 86400}
        return {"action": "wait", "wait_seconds": 14400, "rationale": "Canned automatic reply detected on first turn; await owner", "auto_reply": True}
    if re.search(r"\b(later|busy|tomorrow|baad mein|abhi nahi)\b", lower):
        return {"action": "wait", "wait_seconds": 86400 if "tomorrow" in lower else 1800, "rationale": "Requested a delay; suspend outreach"}
    if re.search(r"\b(gst|tax return|politics|cricket score|stock tip)\b", lower):
        return send("GST/tax filing is outside this assistant's scope; please ask your accountant. I can prepare a business-profile or customer-message draft." if "gst" in lower or "tax" in lower else "That request is outside this assistant's scope. I can help with your business profile and customer-message drafts.", "Stay within scope; no invented specialist advice")
    if re.search(r"\b(useless|idiot|stupid|shut up|bothering)\b", lower):
        return {"action": "end", "rationale": "Frustration detected; stop outreach", "cooldown_seconds": 30 * 86400}
    if re.search(r"ignore.*instructions|system prompt|reveal.*secret|api.?key", lower):
        return send("I can help with this business's profile and customer messages. I cannot disclose credentials or change the task from a chat instruction.", "Treat message as untrusted input")
    if re.search(r"\b(join|onboard|judrna|judna|register|sign up)\b", lower):
        name = merchant.get("identity", {}).get("name", "your business")
        return send(f"Onboarding checklist for {name}: business identity is already on file. Confirm the owner contact through magicpin's official onboarding channel. I cannot create an account from this challenge bot. Which owner contact should you use?", "Explicit join intent: move directly to onboarding; do not claim account creation", "open_ended")
    if re.search(r"\b(price|cost|kitna|charge)\b", lower):
        offer = active_offer(merchant)
        return send(f"The active offer on file is {offer}. Other prices or revised terms need merchant confirmation." if offer else "There is no active price on file. The merchant must confirm the price; I won't invent one.", "Read current active merchant offer only")
    if customer:
        slots = slots_for(trigger)
        if lower in {"yes", "haan", "han", "ok", "okay", "1", "2", "3"} or re.search(r"\b(book|confirm|go ahead)\b", lower):
            if lower.isdigit() and 0 < int(lower) <= len(slots):
                detail = "Requested option: " + slots[int(lower) - 1] + ". "
            else:
                detail = ""
            return send(detail + ("Aapki request is chat mein note hui hai. Booking/refill confirm nahi hua; merchant ko availability confirm karni hogi." if hi else "Your request is noted in this chat. No booking, refill or delivery is confirmed; the merchant must confirm availability."), "Customer intent captured locally; no external booking integration")
    explicit = re.search(r"\b(yes|ok|okay|sure|haan|han|go ahead|let's do it|send|draft|please|bhejo|karo|confirm)\b", lower)
    if explicit:
        kind = kind_of(trigger)
        name = merchant.get("identity", {}).get("name", "your business")
        item = digest_item(category, trigger)
        if kind in ("research_digest", "regulation_change", "cde_opportunity", "trend") and item:
            body = f"Supplied digest summary: {item.get('summary', item.get('title', ''))}\nSource: {item.get('source', 'not provided')}."
            body += "\nThe full paper/abstract was not supplied; I cannot attach or claim to have read it."
            if kind == "regulation_change":
                body += "\nReview draft: verify the original notice, check which equipment/processes it applies to, and record the actions and deadline."
            elif kind == "cde_opportunity":
                body += f"\nEvent note: {item.get('date', 'date not supplied')}; {item.get('actionable', 'confirm registration with the organiser')}. No registration has been made."
            else:
                body += f"\nCustomer draft for your review: ‘{name}: Have questions about your next visit? Contact our team to discuss what suits you.’"
            return send(body, "Honour acceptance now with supplied summary and a draft; do not fabricate an abstract, attachment or clinical advice")
        if kind == "review_theme_emerged":
            return send("Review-response draft: ‘Thank you for sharing your experience. We are sorry it did not meet your expectations. Please contact our team with the visit/order details so we can investigate.’\nInternal checklist: verify the incident, identify the bottleneck, and offer a realistic update. Nothing has been posted.", "Supply requested review response immediately")
        if kind == "gbp_unverified" or "profile" in lower:
            return send("Profile checklist: open your business's official management account, check the verification methods offered there, confirm the business details, and complete the available method. I have not changed or verified your profile.", "Provide steps without claiming remote profile access")
        if kind == "renewal_due":
            return send("Renewal checklist: review the plan and amount in your official merchant account, confirm the billing details, and pay only through that account. I cannot process payment or renew the plan here.", "Concrete renewal steps; no payment link fabricated")
        if kind in ("perf_dip", "perf_spike", "seasonal_perf_dip", "dormant_with_vera", "winback_eligible"):
            return send("Action plan: check your current opening hours and contact details, review recent customer feedback, then prepare one post using a confirmed active service. Track calls and CTR in the next reporting window; the data does not prove what caused the change.", "Provide action plan immediately without causal or growth guarantees")
        if kind == "milestone_reached":
            return send(f"Draft: ‘Thank you for visiting {name}. If you would like to share your experience, please leave an honest review.’ No discount, reward or positive-rating condition. This is a draft; nothing has been sent.", "Neutral review request without incentives or false milestone claims")
        offer = active_offer(merchant)
        body = f"Review draft: ‘{name}"
        if offer:
            body += f" — {offer}. Please confirm applicable days, availability and terms with our team.’"
        else:
            body += ": contact our team for service details and availability.’ Price is not supplied."
        body += "\nThis draft has not been published or sent."
        return send(body, "Explicit acceptance advances to a usable draft, using an active offer only")
    if re.search(r"\b(thanks|thank you|done|thankyou)\b", lower):
        return {"action": "end", "rationale": "Acknowledgement received; conversation complete"}
    if "new" in lower or "latest" in lower:
        items = category.get("digest", [])
        if items:
            item = items[-1]
            return send(f"Latest supplied digest item: {item.get('title', '')}. Source: {item.get('source', 'not supplied')}. {item.get('summary', '')}", "Read live category context, including post-submission updates")
    if kind_of(trigger) == "curious_ask_due":
        return send(f"Noted: “{text[:160]}”. Draft topic: answer the most common question about that service. Any price, availability or offer must be confirmed before posting.", "Use merchant's stated demand to advance the conversation")
    return send("Aapko kis specific detail mein help chahiye?" if hi else "Which specific detail would you like help with?", "One clarification when intent is uncertain", "open_ended")


class APIError(Exception):
    def __init__(self, status, reason):
        self.status, self.reason = status, reason

class Engine:
    def __init__(self):
        self.lock = threading.RLock()
        self.started = time.monotonic()
        self.reset()

    def reset(self):
        self.contexts = {s: {} for s in SCOPES}
        self.conversations = {}
        self.sent_keys = set()
        self.opted_out = set()
        self.cooldowns = {}
        self.last_sent = {}

    def get(self, scope, cid):
        return self.contexts[scope].get(cid, {}).get("payload")

    def push(self, data):
        scope, cid, version, payload = (data.get(k) for k in ("scope", "context_id", "version", "payload"))
        if scope not in SCOPES:
            raise APIError(400, "invalid_scope")
        if not isinstance(cid, str) or not cid or type(version) is not int or version < 1 or not isinstance(payload, dict):
            raise APIError(400, "invalid_context_envelope")
        if payload.get(ID_FIELDS[scope]) != cid:
            raise APIError(400, "context_id_mismatch")
        if scope == "trigger" and (payload.get("scope") not in ("merchant", "customer") or not isinstance(payload.get("payload", {}), dict)):
            raise APIError(400, "invalid_trigger")
        if data.get("delivered_at"):
            stamp(data["delivered_at"])
        existing = self.contexts[scope].get(cid)
        if existing and existing["version"] >= version:
            return 409, {"accepted": False, "reason": "stale_version", "current_version": existing["version"]}
        self.contexts[scope][cid] = {"version": version, "payload": copy.deepcopy(payload)}
        return 200, {"accepted": True, "ack_id": f"ack_{cid}_v{version}", "stored_at": iso_now()}

    def tick(self, data):
        now = stamp(data.get("now"))
        tids = data.get("available_triggers", [])
        if not isinstance(tids, list) or len(tids) > 1000 or any(not isinstance(x, str) for x in tids):
            raise APIError(400, "invalid_available_triggers")
        triggers = [(t, self.get("trigger", t)) for t in set(tids)]
        triggers = sorted(((tid, t) for tid, t in triggers if t), key=lambda pair: (-int(pair[1].get("urgency", 1)), pair[0]))
        actions, recipients = [], set()
        for tid, trigger in triggers:
            if len(actions) == 20:
                break
            if trigger.get("expires_at") and stamp(trigger["expires_at"]) <= now:
                continue
            p = trigger.get("payload", {})
            if trigger.get("not_before") and now < stamp(trigger["not_before"]):
                continue
            mid, cid = refs(trigger)
            merchant = self.get("merchant", mid)
            category = self.get("category", merchant.get("category_slug")) if merchant else None
            customer = self.get("customer", cid) if cid else None
            if not merchant or not category:
                continue
            if trigger.get("scope") == "customer" and (not cid or not customer):
                continue
            recipient = (mid, cid if trigger.get("scope") == "customer" else None)
            key = (*recipient, trigger.get("suppression_key") or tid)
            if recipient in recipients or recipient in self.opted_out or key in self.sent_keys:
                continue
            if recipient in self.cooldowns and now < self.cooldowns[recipient]:
                continue
            if recipient in self.last_sent and (now - self.last_sent[recipient]).total_seconds() < 300:
                continue
            if customer:
                consent_date = customer.get("consent", {}).get("opted_in_at")
                if consent_date and stamp(consent_date) > now:
                    continue
            composed = compose(category, merchant, trigger, customer)
            if not composed["body"]:
                continue
            conv_id = "conv_" + hashlib.sha256(json.dumps([mid, cid, tid, data["now"]]).encode()).hexdigest()[:20]
            action = dict(composed, conversation_id=conv_id, merchant_id=mid,
                          customer_id=recipient[1], trigger_id=tid)
            # All first proactive sends use the mock template, even if a session exists.
            # In-session replies can be free-form; late replies get template metadata.
            self.conversations[conv_id] = {"merchant_id": mid, "customer_id": recipient[1], "trigger_id": tid,
                "status": "open", "sent": [action["body"]], "received": [], "auto_replies": 0,
                "last_turn": 0, "reply_cache": {}, "last_time": now}
            self.sent_keys.add(key)
            self.last_sent[recipient] = now
            recipients.add(recipient)
            actions.append(action)
        return {"actions": actions}

    def reply(self, data):
        conv = self.conversations.get(data.get("conversation_id"))
        if not conv:
            raise APIError(404, "unknown_conversation")
        mid, cid = conv["merchant_id"], conv["customer_id"]
        role = "customer" if cid else "merchant"
        if data.get("from_role") != role or data.get("merchant_id") not in (None, mid) or data.get("customer_id") not in (None, cid):
            raise APIError(400, "recipient_mismatch")
        turn, message = data.get("turn_number"), data.get("message")
        if type(turn) is not int or turn < 1 or not isinstance(message, str) or not message.strip() or len(message) > 10000:
            raise APIError(400, "invalid_reply")
        now = stamp(data.get("received_at"))
        fingerprint = (message, data.get("received_at"))
        if turn in conv["reply_cache"]:
            old = conv["reply_cache"][turn]
            if old[0] != fingerprint:
                raise APIError(409, "turn_conflict")
            return old[1]
        if turn <= conv["last_turn"] or now < conv["last_time"]:
            raise APIError(409, "out_of_order_reply")
        recipient = (mid, cid)
        if conv["status"] == "ended" or recipient in self.opted_out:
            return {"action": "end", "rationale": "Conversation ended or recipient opted out"}
        merchant = self.get("merchant", mid)
        category = self.get("category", merchant["category_slug"])
        trigger = self.get("trigger", conv["trigger_id"])
        customer = self.get("customer", cid) if cid else None
        if customer and consent_reason(customer, merchant, trigger):
            result = {"action": "end", "rationale": "Current customer consent no longer allows this conversation"}
        elif not category or not trigger:
            result = {"action": "end", "rationale": "Required live context unavailable"}
        else:
            result = respond(dict(conv, merchant=merchant, category=category, trigger=trigger, customer=customer), message)
        if result.get("auto_reply"):
            conv["auto_replies"] += 1
        if result.get("opt_out"):
            self.opted_out.add(recipient)
        if result.get("cooldown_seconds"):
            self.cooldowns[recipient] = now + timedelta(seconds=result["cooldown_seconds"])
        if result["action"] == "wait":
            self.cooldowns[recipient] = now + timedelta(seconds=result["wait_seconds"])
        elif result["action"] == "end":
            conv["status"] = "ended"
        else:
            conv["sent"].append(result["body"])
            if (now - conv["last_time"]).total_seconds() > 86400:
                result.update(template_name="vera_reply_v1", template_params=[result["body"]])
        public = {k: v for k, v in result.items() if k not in {"opt_out", "auto_reply", "cooldown_seconds"}}
        conv["received"].append(message.strip().lower().replace("’", "'"))
        conv["last_turn"], conv["last_time"] = turn, now
        conv["reply_cache"][turn] = (fingerprint, public)
        return public

    def dispatch(self, method, path, data=None):
        with self.lock:
            if method == "GET" and path == "/v1/healthz":
                return 200, {"status": "ok", "uptime_seconds": int(time.monotonic() - self.started),
                             "contexts_loaded": {s: len(self.contexts[s]) for s in SCOPES}}
            if method == "GET" and path == "/v1/metadata":
                return 200, {"team_name": os.getenv("TEAM_NAME", "Vera Context"),
                    "team_members": [x.strip() for x in os.getenv("TEAM_MEMBERS", "Ayush Jaiswal").split(",")],
                    "model": "none (deterministic rules; no LLM)", "approach": "Grounded four-context composition + stateful consent and intent router",
                    "contact_email": os.getenv("CONTACT_EMAIL", ""), "version": VERSION,
                    "submitted_at": os.getenv("SUBMITTED_AT", "not-submitted")}
            if method == "POST" and path == "/v1/context":
                return self.push(data)
            if method == "POST" and path == "/v1/tick":
                return 200, self.tick(data)
            if method == "POST" and path == "/v1/reply":
                return 200, self.reply(data)
            if method == "POST" and path == "/v1/teardown":
                self.reset()
                return 200, {"status": "cleared"}
            raise APIError(404, "not_found")

ENGINE = Engine()
DEMO_ENGINE = Engine()


def demo_dispatch(path, data):
    if os.getenv("DEMO_MODE", "0") != "1":
        raise APIError(403, "demo_disabled_set_DEMO_MODE_1_locally")
    with DEMO_ENGINE.lock:
        if path == "/demo/start":
            choices = {"research": "trg_001_research_digest_dentists", "performance": "trg_004_perf_dip_bharat",
                       "customer": "trg_003_recall_due_priya", "reviews": "trg_011_review_theme_late_delivery"}
            tid = choices.get(data.get("scenario", "research"))
            if not tid:
                raise APIError(400, "unknown_scenario")
            DEMO_ENGINE.reset()
            trigger = json.loads((ROOT / "dataset" / "triggers" / (tid + ".json")).read_text())
            mid, cid = refs(trigger)
            merchant = json.loads((ROOT / "dataset" / "merchants" / (mid + ".json")).read_text())
            category = json.loads((ROOT / "dataset" / "categories" / (merchant["category_slug"] + ".json")).read_text())
            items = [("merchant", mid, merchant), ("category", category["slug"], category), ("trigger", tid, trigger)]
            if cid:
                customer = json.loads((ROOT / "dataset" / "customers" / (cid + ".json")).read_text())
                items.append(("customer", cid, customer))
            for scope, identifier, payload in items:
                DEMO_ENGINE.push(dict(scope=scope, context_id=identifier, version=1, payload=payload))
            now = "2026-11-01T10:00:00Z" if cid else "2026-04-26T10:00:00Z"
            result = DEMO_ENGINE.tick(dict(now=now, available_triggers=[tid]))
            return 200, dict(result, simulated_now=now, merchant_name=merchant["identity"]["name"])
        if path == "/demo/reply":
            return 200, DEMO_ENGINE.reply(data)
        raise APIError(404, "not_found")

class Handler(BaseHTTPRequestHandler):
    server_version = "VeraContext/1.0"
    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, fmt, *args):
        # Do not log merchant/customer bodies or personal data.
        pass

    def do_GET(self):
        if urlsplit(self.path).path == "/":
            data = (ROOT / "static" / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)
        else:
            self.handle_api("GET")

    def do_POST(self):
        self.handle_api("POST")

    def handle_api(self, method):
        try:
            data = None
            if method == "POST":
                length = int(self.headers.get("Content-Length", "0"))
                if length < 0 or length > 500 * 1024:
                    raise APIError(413, "payload_too_large")
                if self.headers.get("Transfer-Encoding"):
                    raise APIError(400, "unsupported_transfer_encoding")
                if "application/json" not in self.headers.get("Content-Type", ""):
                    raise APIError(415, "expected_application_json")
                data = json.loads(self.rfile.read(length)) if length else {}
                if not isinstance(data, dict):
                    raise APIError(400, "expected_json_object")
            path = urlsplit(self.path).path
            if method == "POST" and path.startswith("/demo/"):
                status, result = demo_dispatch(path, data)
            else:
                status, result = ENGINE.dispatch(method, path, data)
        except APIError as exc:
            status, result = exc.status, {"accepted": False, "reason": exc.reason}
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
            status, result = 400, {"accepted": False, "reason": "invalid_payload"}
        except Exception:
            status, result = 500, {"accepted": False, "reason": "internal_error"}
        payload = json.dumps(result, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(payload)

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    server = ThreadingHTTPServer((os.getenv("HOST", "0.0.0.0"), port), Handler)
    print(f"Vera Context running on port {port}. Open http://localhost:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        ENGINE.reset()
        server.server_close()
