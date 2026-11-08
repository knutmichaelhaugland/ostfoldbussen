"""HTML-maler (ren stdlib). Ingen eksterne ressurser, ingen hemmeligheter.

All dynamisk tekst escapes med html.escape før den settes inn.
"""

from __future__ import annotations

from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

SITE_URL = "https://ostfoldbussen.no"
PAGE_PATHS = {
    "Slik fungerer det": "/slik-fungerer-det",
    "Om Østfoldbussen": "/om",
    "Personvern": "/personvern",
    "Kontakt": "/kontakt",
    "Data og lisens": "/data",
    "Driftsstatus": "/status",
}

BASE_CSS = """
:root{color-scheme:light dark;--bg:#f7f7f5;--fg:#1d1d1b;--muted:#555;--card:#fff;--line:#d7d7d2;--accent:#0b5c3b}
@media (prefers-color-scheme:dark){:root{--bg:#141414;--fg:#eee;--muted:#aaa;--card:#1d1d1d;--line:#333;--accent:#6fd3a8}}
*{box-sizing:border-box}
body{margin:0;font-family:system-ui,-apple-system,"Segoe UI",sans-serif;background:var(--bg);color:var(--fg);line-height:1.55}
header{background:var(--card);border-bottom:1px solid var(--line)}
.wrap{max-width:56rem;margin:0 auto;padding:1rem}
nav a{margin-right:1rem;color:var(--accent);text-decoration:none}
nav a:hover{text-decoration:underline}
main{max-width:56rem;margin:0 auto;padding:1rem 1rem 3rem}
h1{font-size:1.6rem;line-height:1.25}
h2{font-size:1.2rem;margin-top:2rem}
.card{background:var(--card);border:1px solid var(--line);border-radius:.5rem;padding:1rem;margin:1rem 0}
.muted{color:var(--muted)}
table{width:100%;border-collapse:collapse;font-size:.9rem}
th,td{text-align:left;padding:.35rem .5rem;border-bottom:1px solid var(--line);vertical-align:top}
code,pre{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.85rem}
pre{overflow:auto;background:var(--card);border:1px solid var(--line);padding:.75rem;border-radius:.4rem}
.badge{display:inline-block;padding:.1rem .5rem;border-radius:1rem;border:1px solid var(--line);font-size:.8rem}
.ok{border-color:#0b5c3b}.bad{border-color:#a33}.warn{border-color:#a76b00}
input[type=text],input[type=password]{width:100%;max-width:22rem;padding:.5rem;border:1px solid var(--line);border-radius:.35rem;background:var(--card);color:var(--fg)}
button{padding:.5rem 1rem;border:1px solid var(--line);border-radius:.35rem;background:var(--accent);color:#fff;cursor:pointer}
footer{max-width:56rem;margin:0 auto;padding:1rem;color:var(--muted);font-size:.85rem}
"""

PUBLIC_CSS = """
:root{--paper:#fbf8f1;--paper-2:#f4efe3;--ink:#14251c;--green:#0f4d34;--green-2:#1d6a4a;--sage:#e7efe5;--clay:#9a4f31;--line:#d9e2d6;--muted:#52645a;--white:#fffdf8;--content-width:1200px;--section-spacing:clamp(3.5rem,7vw,6rem)}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--paper);color:var(--ink);font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;font-size:1.075rem;line-height:1.65}
a{color:var(--green);text-underline-offset:.18em}
a:hover{color:var(--green-2)}
a:focus-visible,button:focus-visible,summary:focus-visible{outline:3px solid var(--clay);outline-offset:3px;border-radius:.2rem}
img,svg{max-width:100%}
.skip{position:absolute;left:-9999px;background:var(--ink);color:var(--white);padding:.7rem 1rem;z-index:200}
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
.skip:focus{left:1rem;top:1rem}
.wrap{width:min(100% - 2.4rem,var(--content-width));margin-inline:auto}
h1,h2,h3{font-family:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;font-weight:700;color:var(--ink);letter-spacing:-.03em;text-wrap:balance}
.kicker{margin:0 0 .65rem;color:var(--clay);font-weight:800;letter-spacing:.13em;text-transform:uppercase;font-size:.8rem}
.site-header{background:var(--white);border-bottom:1px solid var(--line);position:relative;z-index:50}
.header-inner{display:flex;align-items:center;justify-content:space-between;gap:1.5rem;padding:1rem 0}
.brand{display:inline-flex;align-items:center;gap:.7rem;text-decoration:none;color:var(--ink)}
.brand-mark{width:46px;height:46px;flex:0 0 auto}
.brand-text{font-size:1.32rem;letter-spacing:-.01em}
.brand-text strong{font-weight:800}
.brand-text span{font-weight:500;color:var(--green)}
.nav-desktop{display:flex;align-items:center;gap:1.8rem}
.nav-desktop a{text-decoration:none;font-weight:650;color:var(--ink);padding:.7rem .1rem;min-height:44px;display:inline-flex;align-items:center}
.nav-desktop a:hover{color:var(--green);text-decoration:underline}
.menu-mobile{display:none;position:relative}
.menu-mobile summary{list-style:none;cursor:pointer;border:1.5px solid var(--green);border-radius:.55rem;padding:.65rem 1rem;min-height:44px;display:inline-flex;align-items:center;font-weight:750;color:var(--green);background:var(--white)}
.menu-mobile summary::-webkit-details-marker{display:none}
.menu-mobile summary:before{content:"☰";margin-right:.5rem;font-size:1.1rem}
.menu-mobile[open] summary:before{content:"×"}
.menu-mobile nav{position:absolute;right:0;top:calc(100% + .5rem);background:var(--white);border:1px solid var(--line);border-radius:.8rem;box-shadow:0 12px 30px rgba(20,37,28,.14);min-width:15rem;padding:.6rem;display:grid}
.menu-mobile nav a{padding:.85rem .85rem;text-decoration:none;color:var(--ink);font-weight:650;border-radius:.4rem;min-height:44px;display:flex;align-items:center}
.menu-mobile nav a:hover{background:var(--sage)}
main{display:block}
.hero{padding:clamp(3rem,6vw,6rem) 0;background:var(--paper)}
.hero-grid{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(0,.9fr);gap:clamp(2rem,5vw,5rem);align-items:center}
.hero-content{min-width:0;max-width:40rem}
.hero h1{font-size:clamp(3rem,5.2vw,5.2rem);line-height:1.04;letter-spacing:-.045em;text-wrap:balance;margin:0 0 .6rem}
.hero .tagline{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;font-size:clamp(1.5rem,2.6vw,2.25rem);line-height:1.2;font-weight:650;color:var(--green);margin:0 0 1.25rem}
.hero .lead{max-width:32rem;font-size:clamp(1.05rem,1.4vw,1.2rem);line-height:1.55;margin:0 0 1.5rem}
.hero-benefits{display:flex;flex-wrap:wrap;gap:.7rem 1.25rem;list-style:none;margin:0;padding:0}
.hero-benefits li{display:inline-flex;align-items:center;gap:.4rem;font-size:.95rem;font-weight:650;color:var(--green)}
.hero-benefits li::before{content:"✓";font-weight:800}
.hero-action{min-width:0;width:100%;justify-self:end}
.number-panel{max-width:none;padding:clamp(1.5rem,3vw,2.5rem);border:1px solid var(--line);border-radius:1.25rem;background:var(--white);box-shadow:0 16px 50px rgba(20,37,28,.06)}
.number-panel-inactive{border-style:dashed}
.number-label{font-size:.8rem;letter-spacing:.09em;text-transform:uppercase;font-weight:750;color:var(--muted);margin:0 0 .5rem}
.number-big{font-size:clamp(2rem,3.8vw,3.5rem);font-weight:800;letter-spacing:-.035em;font-variant-numeric:tabular-nums;font-feature-settings:"tnum";line-height:1.12;white-space:nowrap;overflow-wrap:normal;margin:0 0 .5rem}
.number-link{color:inherit;text-decoration:none;border-bottom:3px solid transparent}
.number-link:hover{text-decoration:underline;text-underline-offset:.12em}
.number-link:focus-visible{outline:3px solid var(--clay);outline-offset:4px;border-radius:.2rem}
.number-placeholder{font-size:1.15rem;font-weight:750;color:var(--ink);margin:0 0 .45rem}
.number-note{margin:.55rem 0 0;color:var(--muted);font-size:.95rem}
.sms-button{display:block;width:100%;min-height:56px;padding:1rem 1.5rem;margin:1.25rem 0 .6rem;border-radius:.75rem;text-align:center;text-decoration:none;font-size:1.1rem;font-weight:800;background:var(--green);color:var(--white)!important}
.sms-button:hover{background:var(--green-2)}
.vcard-button{display:block;width:100%;min-height:48px;padding:.8rem;margin:0;border:0;border-radius:.5rem;text-align:center;text-decoration:underline;text-underline-offset:.2em;font-weight:650;color:var(--green)!important;background:transparent}
.vcard-button:hover{background:var(--sage)}
.vcard-button:focus-visible{outline:3px solid var(--clay);outline-offset:3px}
.vcard-tip{display:none}
.contact-tip{margin:1.2rem 0 0;padding-left:1rem;border-left:3px solid var(--clay);color:var(--ink);max-width:34rem;font-size:.98rem}
.conversation-demo{padding:var(--section-spacing) 0;background:var(--sage)}
.conversation-layout{display:grid;grid-template-columns:minmax(0,.9fr) minmax(0,1.1fr);gap:clamp(2rem,5vw,5rem);align-items:center}
.conversation-intro{max-width:34rem}
.conversation-intro h2{font-size:clamp(2rem,4vw,3.5rem);line-height:1.1;margin:0 0 1rem}
.conversation-intro p{font-size:1.1rem;max-width:32rem}
.conversation-note{margin-top:1.2rem;padding-top:1rem;border-top:1px solid var(--line);color:var(--muted);font-size:.98rem!important}
.conversation-visual{min-width:0}
.phone{width:min(100%,360px);margin-inline:auto;background:#1b2a22;border-radius:2.1rem;padding:.7rem;box-shadow:0 18px 45px rgba(15,77,52,.14);transform:none}
.phone-screen{background:var(--paper);border-radius:1.6rem;overflow:hidden;border:1px solid #0d2018}
.phone-top{background:var(--green);color:var(--white);padding:.8rem 1rem;font-weight:750;font-size:.95rem;display:flex;justify-content:space-between;align-items:center;gap:.5rem}
.phone-top span{opacity:.8;font-size:.75rem;font-weight:600;white-space:nowrap}
.chat{padding:.9rem .8rem 1rem;display:grid;gap:.55rem}
.bubble{max-width:88%;padding:.6rem .75rem;border-radius:.9rem;font-size:.93rem;line-height:1.45}
.bubble.in{background:var(--sage);border-bottom-left-radius:.25rem;justify-self:start}
.bubble.out{background:var(--green);color:var(--white);border-bottom-right-radius:.25rem;justify-self:end}
.bubble small{display:block;margin-top:.25rem;opacity:.75;font-size:.72rem}
.composer{margin:.1rem .8rem .9rem;border:1px solid var(--line);border-radius:2rem;padding:.5rem .8rem;color:var(--muted);font-size:.85rem;background:var(--white)}
.illustration-caption{margin:.9rem 0 0;color:var(--muted);font-size:.9rem;text-align:center;max-width:34rem;margin-inline:auto}
section.band{padding:var(--section-spacing) 0}
.sage{background:var(--sage)}
.ivory{background:var(--paper-2)}
.section-head{display:grid;grid-template-columns:.9fr 1.1fr;gap:clamp(1.5rem,4vw,4rem);align-items:end;margin-bottom:2.3rem}
.section-head h2{font-size:clamp(2rem,4.2vw,3rem);line-height:1.1;margin:0}
.section-head p{margin:0;color:var(--muted);font-size:1.08rem;max-width:38rem}
.section-head.single{grid-template-columns:1fr}
.section-note{margin:1.5rem 0 0;color:var(--muted);font-size:1.05rem;max-width:44rem}
.section-sub{margin:.45rem 0 2rem;color:var(--muted);font-size:1.1rem;max-width:46rem}
.steps{display:grid;grid-template-columns:repeat(3,1fr);gap:1.4rem;counter-reset:step;list-style:none;padding:0;margin:0}
.step{position:relative;padding-top:3.4rem}
.step:before{counter-increment:step;content:counter(step);position:absolute;top:0;left:0;width:2.7rem;height:2.7rem;border-radius:50%;background:var(--green);color:var(--white);display:grid;place-items:center;font-weight:800;font-size:1.1rem}
.step h3{font-size:1.2rem;margin:0 0 .35rem;font-family:system-ui,sans-serif;font-weight:750}
.step p{margin:0;color:var(--muted)}
.steps-list{counter-reset:item;list-style:none;padding:0;display:grid;gap:1rem}
.steps-list li{counter-increment:item;position:relative;padding-left:3.2rem}
.steps-list li:before{content:counter(item);position:absolute;left:0;top:0;width:2.3rem;height:2.3rem;border-radius:50%;background:var(--green);color:var(--white);display:grid;place-items:center;font-weight:800}
.benefits-head{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(0,.9fr);gap:clamp(1.5rem,5vw,4rem);align-items:end;margin-bottom:2rem}
.benefits-head h2{font-size:clamp(2rem,4.2vw,3rem);line-height:1.1;margin:0}
.benefits-head p{margin:0;color:var(--muted);max-width:34rem}
.primary-benefits{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,18rem),1fr));gap:1.2rem;list-style:none;padding:0;margin:0}
.primary-benefit{min-width:0;background:var(--white);border:1px solid var(--line);border-radius:1rem;padding:1.4rem;display:grid;grid-template-columns:auto minmax(0,1fr);gap:.7rem;align-items:start}
.primary-benefit .tick{grid-row:span 2}
.primary-benefit h3{font-family:system-ui,sans-serif;font-size:1.1rem;margin:0;font-weight:750}
.primary-benefit p{margin:0;color:var(--muted);font-size:.98rem}
.tick{width:1.7rem;height:1.7rem;border-radius:50%;background:var(--green);color:var(--white);display:grid;place-items:center;font-size:.95rem;font-weight:900;margin-top:.1rem}
.secondary-benefits{margin-top:2rem;padding-top:1.3rem;border-top:1px solid var(--line);display:grid;grid-template-columns:auto 1fr;gap:1.2rem;align-items:baseline}
.secondary-benefits h3{font-family:system-ui,sans-serif;font-size:.85rem;letter-spacing:.1em;text-transform:uppercase;margin:0;color:var(--muted);white-space:nowrap}
.secondary-benefits ul{display:flex;flex-wrap:wrap;gap:.5rem 1.4rem;list-style:none;padding:0;margin:0}
.secondary-benefits li{color:var(--ink);font-size:.98rem}
.secondary-benefits li::before{content:"·";color:var(--clay);font-weight:900;margin-right:.4rem}
.featured-examples{display:grid;grid-template-columns:repeat(3,1fr);gap:1rem}
.example-featured{background:var(--white);border:1px solid var(--line);border-radius:.9rem;padding:1.3rem 1.4rem;font-size:1.08rem;line-height:1.5;font-weight:650;margin:0}
.example-featured:before{content:"“";color:var(--clay);font-family:Georgia,serif;font-size:1.7rem;line-height:0;vertical-align:-.2rem;margin-right:.15rem}
.example-more{margin:1.4rem 0 0;color:var(--muted);max-width:46rem}
.example-grid{display:grid;grid-template-columns:1fr 1fr;gap:.9rem 1.6rem}
.example{background:var(--white);border:1px solid var(--line);border-radius:.7rem;padding:.85rem 1rem;font-weight:600}
.example:before{content:"“";color:var(--clay);font-family:Georgia,serif;font-size:1.6rem;line-height:0;vertical-align:-.15rem;margin-right:.2rem}
.pricing{background:var(--green);color:var(--white);border-radius:1.2rem;padding:clamp(2rem,4vw,3.4rem);display:grid;grid-template-columns:.8fr 1.2fr;gap:2.2rem;align-items:center}
.pricing .kicker{color:#f7d9a8}
.pricing h2{color:var(--white);margin:0 0 .8rem;font-size:clamp(2rem,4vw,3rem);line-height:1.1}
.pricing .free{font-family:"Iowan Old Style",Georgia,serif;font-size:clamp(3.4rem,7vw,5.6rem);font-weight:700;line-height:1;color:#f7d9a8;margin:0}
.pricing p{color:#eaf3ec;margin:0 0 .8rem;max-width:40rem}
.pricing p:last-child{margin-bottom:0}
.why-grid{display:grid;grid-template-columns:1.1fr .9fr;gap:clamp(1.5rem,5vw,4rem);align-items:start}
.why-grid h2{font-size:clamp(2rem,4.2vw,3.2rem);line-height:1.1;margin:0 0 1rem}
.why-grid p{max-width:38rem}
.pullquote{margin:0;border-left:5px solid var(--clay);padding:.2rem 0 .2rem 1.2rem;font-family:"Iowan Old Style",Georgia,serif;font-size:1.5rem;line-height:1.35;color:var(--green)}
.cta{background:var(--paper-2);border-top:1px solid var(--line);border-bottom:1px solid var(--line);padding:clamp(2.5rem,5vw,4rem) 0}
.cta-inner{display:grid;grid-template-columns:1.1fr .9fr;gap:2.5rem;align-items:center}
.cta-content h2{margin:0 0 .6rem;font-size:clamp(2rem,4vw,3rem);line-height:1.1}
.cta-content p{margin:0;color:var(--muted);max-width:34rem}
.cta-action .number-panel{max-width:32rem;margin-left:auto}
.site-footer{background:var(--white);padding:3.2rem 0 1.8rem;color:var(--muted);font-size:.95rem}
.footer-grid{display:grid;grid-template-columns:1.4fr 1fr 1fr;gap:2.5rem;align-items:start}
.footer-brand .brand-text{font-size:1.15rem}
.footer-brand p{margin:.7rem 0 0;max-width:27rem}
.footer-credit{font-size:.9rem}
.footer-col h3{font-family:system-ui,sans-serif;font-size:.8rem;letter-spacing:.12em;text-transform:uppercase;color:var(--ink);margin:0 0 .6rem}
.footer-col nav{display:grid;gap:.4rem}
.footer-col a{color:var(--ink);text-decoration:none;font-weight:550;min-height:32px;display:inline-flex;align-items:center}
.footer-col a:hover{text-decoration:underline}
.footer-bottom{border-top:1px solid var(--line);margin-top:2.2rem;padding-top:1.1rem;font-size:.85rem;display:flex;flex-wrap:wrap;gap:.5rem 1.5rem;justify-content:space-between}
.page-hero{background:var(--sage);padding:clamp(2.4rem,5vw,4rem) 0;border-bottom:1px solid var(--line)}
.page-hero h1{font-size:clamp(2.2rem,5vw,3.6rem);margin:0 0 .5rem}
.page-hero p{margin:0;max-width:44rem;font-size:1.12rem;color:var(--muted)}
.prose{max-width:68ch;padding:clamp(2rem,5vw,3.5rem) 0 3rem}
.prose h2{font-size:1.7rem;margin:2.4rem 0 .6rem}
.prose h3{font-size:1.15rem;font-family:system-ui,sans-serif;margin:1.4rem 0 .3rem}
.prose ul,.prose ol{padding-left:1.3rem}
.prose li{margin:.35rem 0}
.prose .note{background:var(--sage);border-radius:.7rem;padding:1rem 1.1rem;color:var(--ink)}
.contact-email{margin:1rem 0;font-size:1.08rem}
.contact-form{max-width:42rem;margin:1.2rem 0 0;display:grid;gap:1.1rem}
.form-field{display:grid;gap:.35rem}
.form-field label{font-weight:700}
.form-field input,.form-field textarea{width:100%;min-height:48px;padding:.8rem .9rem;border:1.5px solid var(--line);border-radius:.55rem;font:inherit;background:var(--white);color:var(--ink)}
.form-field textarea{min-height:9rem;resize:vertical}
.form-field input:focus,.form-field textarea:focus{outline:3px solid var(--clay);outline-offset:2px;border-color:var(--green)}
.form-consent{display:grid;grid-template-columns:auto minmax(0,1fr);gap:.6rem;align-items:start;font-size:.96rem}
.form-consent input{width:1.3rem;height:1.3rem;margin:.15rem 0 0}
.form-status{padding:1rem 1.1rem;border-radius:.6rem;margin:0 0 .4rem;font-weight:650}
.form-status.ok{background:var(--sage);color:var(--ink)}
.form-status.error{background:#fbe9e4;color:#7a1f12}
.optional{font-weight:500;color:var(--muted)}
.contact-submit{max-width:20rem}
.sms-button:disabled{opacity:.55;cursor:not-allowed}
.hp{position:absolute;left:-9999px;width:1px;height:1px;overflow:hidden}
.table-wrap{overflow-x:auto;margin:1.2rem 0;max-width:100%}
.subprocessors{width:100%;border-collapse:collapse;background:var(--white);border:1px solid var(--line);font-size:.95rem}
.subprocessors caption{text-align:left;font-weight:750;padding:0 0 .5rem;color:var(--ink)}
.subprocessors th,.subprocessors td{text-align:left;padding:.7rem .8rem;border-bottom:1px solid var(--line);vertical-align:top}
.subprocessors th{background:var(--paper-2);font-size:.8rem;text-transform:uppercase;letter-spacing:.05em}
.subprocessors .small{font-size:.82rem;color:var(--muted)}
@media (max-width:620px){
 .table-wrap{overflow:visible}
 .subprocessors thead{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0)}
 .subprocessors,.subprocessors tbody,.subprocessors tr,.subprocessors td{display:block;width:100%}
 .subprocessors{background:transparent;border:0}
 .subprocessors tr{background:var(--white);border:1px solid var(--line);border-radius:.8rem;padding:.9rem 1rem;margin:0 0 .8rem}
 .subprocessors td{border:0;padding:.25rem 0}
 .subprocessors td:before{content:attr(data-label);display:block;font-size:.72rem;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);font-weight:750;margin-bottom:.1rem}
 .subprocessors td:first-child:before{display:none}
}
.status-table{width:100%;border-collapse:collapse;background:var(--white);border:1px solid var(--line);border-radius:.7rem;overflow:hidden}
.status-table th,.status-table td{text-align:left;padding:.7rem .9rem;border-bottom:1px solid var(--line)}
.status-table th{background:var(--paper-2);font-size:.85rem;text-transform:uppercase;letter-spacing:.06em}
.status-list{list-style:none;padding:0;margin:1.2rem 0;display:grid;gap:.6rem;max-width:34rem}
.status-list li{display:flex;justify-content:space-between;gap:1rem;align-items:center;background:var(--white);border:1px solid var(--line);border-radius:.6rem;padding:.85rem 1rem;font-size:1.08rem}
.status-list strong{font-weight:750;white-space:nowrap}
.status-list .ok{color:var(--green)}
.status-list .bad{color:#8a1f1f}
.status-list .warn{color:var(--clay)}
.status-notice{background:#fff4e8;border-left:5px solid var(--clay);border-radius:.6rem;padding:1rem 1.1rem;color:var(--ink);font-weight:650;max-width:44rem;margin:1rem 0 1.4rem}
.badge{display:inline-block;padding:.15rem .6rem;border-radius:1rem;border:1px solid var(--line);font-size:.82rem;font-weight:700}
.badge.ok{border-color:var(--green);color:var(--green)}
.badge.bad{border-color:#a33;color:#8a1f1f}
.badge.warn{border-color:var(--clay);color:var(--clay)}
@media (max-width:980px){
 .hero-grid,.conversation-layout{grid-template-columns:1fr;gap:2.5rem}
 .hero-content,.conversation-intro{max-width:42rem}
 .hero-action{justify-self:stretch}
 .number-big{white-space:normal;overflow-wrap:anywhere}
 .section-head,.benefits-head,.pricing,.why-grid,.cta-inner,.footer-grid{grid-template-columns:1fr}
 .steps{grid-template-columns:1fr}
 .featured-examples{grid-template-columns:1fr}
 .cta-action .number-panel{margin-left:0}
 .nav-desktop{display:none}
 .menu-mobile{display:block}
}
@media (max-width:620px){
 .wrap{width:min(100% - 1.7rem,1200px)}
 .hero{padding:2.5rem 0 3rem}
 .hero h1{font-size:clamp(2.5rem,10vw,3.5rem)}
 .hero .lead{font-size:1.08rem}
 .number-panel{padding:1.4rem}
 .number-big{font-size:clamp(1.8rem,9vw,2.6rem)}
 .sms-button{min-height:54px}
 .phone{width:min(100%,320px)}
 .primary-benefits{grid-template-columns:1fr}
 .secondary-benefits{grid-template-columns:1fr;gap:.6rem}
 .secondary-benefits h3{white-space:normal}
 .benefits-head p,.section-head p{font-size:1rem}
 .header-inner{padding:.75rem 0}
 .brand-text{font-size:1.15rem}
 .brand-mark{width:38px;height:38px}
 .pricing{padding:1.5rem}
 .example-grid{grid-template-columns:1fr}
 .footer-bottom{flex-direction:column}
 .footer-col a{min-height:44px}
 .brand{min-height:44px}
}
@media (max-width:360px){
 .number-big{font-size:1.72rem}
 .hero-benefits{flex-direction:column;gap:.35rem}
}
@media (prefers-reduced-motion:reduce){*,*::before,*::after{scroll-behavior:auto!important;animation-duration:.01ms!important;transition-duration:.01ms!important}}
@media (prefers-reduced-motion:no-preference){.sms-button,.vcard-button,.nav-desktop a{transition:background-color .15s ease,color .15s ease}}
@media print{header.site-header,.site-footer,.sms-button,.vcard-button,.menu-mobile{display:none}body{background:#fff}.hero,.band,.cta,.conversation-demo{padding:1rem 0}}
"""


LOGO_SVG = (
    '<svg class="brand-mark" viewBox="0 0 48 48" aria-hidden="true" focusable="false">'
    '<rect width="48" height="48" rx="13" fill="#0f4d34"/>'
    '<path d="M12 33c0-9.4 7.6-17 17-17h7" fill="none" stroke="#fbf8f1" stroke-width="4" stroke-linecap="round"/>'
    '<circle cx="12" cy="33" r="4.6" fill="#b36744"/>'
    '<circle cx="36" cy="16" r="4.6" fill="#fbf8f1"/>'
    "</svg>"
)


def _brand() -> str:
    return (f'<a class="brand" href="/" aria-label="Østfoldbussen – til forsiden">'
            f'{LOGO_SVG}<span class="brand-text"><strong>Østfold</strong><span>bussen</span></span></a>')


def _menu() -> str:
    return (
        '<div class="nav-desktop">'
        '<a href="/slik-fungerer-det">Slik fungerer det</a>'
        '<a href="/om">Om</a>'
        '<a href="/kontakt">Kontakt</a>'
        "</div>"
        '<details class="menu-mobile"><summary>Meny</summary><nav aria-label="Hovedmeny">'
        '<a href="/">Forside</a>'
        '<a href="/slik-fungerer-det">Slik fungerer det</a>'
        '<a href="/om">Om Østfoldbussen</a>'
        '<a href="/kontakt">Kontakt</a>'
        "</nav></details>"
    )


def _display_number(raw: str) -> str:
    digits = "".join(ch for ch in str(raw) if ch.isdigit())
    if len(digits) == 8:
        digits = "47" + digits
    if len(digits) == 10 and digits.startswith("47"):
        return f"+47 {digits[2:5]} {digits[5:7]} {digits[7:]}"
    return raw


def _public_number_block(public: dict) -> str:
    if public.get("sms_enabled"):
        pretty = _display_number(public.get("sms_number", ""))
        digits = "".join(ch for ch in str(public.get("sms_number", "")) if ch.isdigit())
        href = "sms:+" + digits if digits else "sms:"
        return (
            '<div class="number-panel">'
            '<p class="number-label">Send SMS til Østfoldbussen</p>'
            f'<p class="number-big"><a class="number-link" href="{escape(href)}" '
            f'aria-label="Send SMS til {escape(pretty)}">{escape(pretty)}</a></p>'
            f'<a class="sms-button" href="{escape(href)}">Send SMS</a>'
            f'<a class="vcard-button" href="/ostfoldbussen.vcf" '
            'download="ostfoldbussen.vcf">Lagre nummeret i kontakter</a>'
            '<p class="number-note">Vanlig SMS-takst kan gjelde. Tjenesten er under '
            'testing, og kan «hikke» litt.</p>'
            "</div>"
        )
    return (
        '<div class="number-panel number-panel-inactive">'
        '<p class="number-label">Send SMS til Østfoldbussen</p>'
        '<p class="number-placeholder">SMS-nummeret er ikke aktivert ennå.</p>'
        '<p class="number-note">Nummeret vises her når tjenesten er klar.</p>'
        "</div>"
    )


def _phone_illustration() -> str:
    return (
        '<div class="phone" aria-hidden="true">'
        '<div class="phone-screen">'
        '<div class="phone-top">Østfoldbussen <span>SMS-eksempel</span></div>'
        '<div class="chat">'
        '<div class="bubble in">Når går buss 22 fra Skredderåsen?<small>Du · 07:42</small></div>'
        '<div class="bubble out">Skredderåsen linje 22: 08:39, 08:46, 08:54. Sanntid der den finnes. '
        '<small>Østfoldbussen</small></div>'
        '<div class="bubble in">Jeg skal til Refsnes<small>Du · 07:43</small></div>'
        '<div class="bubble out">Fra Skredderåsen til Refsnes: 08:54 linje 22, bytte Moss bussterminal, 09:05 linje 20, framme 09:18. Rutetider.<small>Østfoldbussen</small></div>'
        "</div>"
        '<div class="composer">Skriv en SMS …</div>'
        '</div></div>'
        '<p class="illustration-caption">Eksempel på SMS-samtale hentet fra Entur '
        "6. november 2026. Rutetider kan endres.</p>"
    )


def _document(title: str, body: str, *, nav: bool = True,
              public: dict | None = None, description: str = "",
              path: str = "/", seo: bool = True) -> str:
    public = public or {}
    description = (description or
                   "Østfoldbussen – bussinformasjon for Østfold på SMS. Uten app, "
                   "smarttelefon eller innlogging.")
    canonical = SITE_URL + path
    seo_head = ""
    if seo:
        seo_head = (
            '<meta name="robots" content="index,follow">'
            f'<link rel="canonical" href="{escape(canonical)}">'
            '<meta property="og:type" content="website">'
            '<meta property="og:site_name" content="Østfoldbussen">'
            f'<meta property="og:title" content="{escape(title)} · Østfoldbussen">'
            f'<meta property="og:description" content="{escape(description)}">'
            f'<meta property="og:url" content="{escape(canonical)}">'
            '<meta property="og:locale" content="nb_NO">'
            '<meta name="twitter:card" content="summary_large_image">'
            '<meta name="twitter:image" content="https://ostfoldbussen.no/og-image.png">'
            '<meta property="og:image" content="https://ostfoldbussen.no/og-image.png">'
            '<meta property="og:image:width" content="1200">'
            '<meta property="og:image:height" content="630">'
            '<meta property="og:image:alt" content="Østfoldbussen – når går bussen? Bare send en SMS.">'
            '<meta name="theme-color" content="#0f4d34">'
            '<script type="application/ld+json">'
            '{"@context":"https://schema.org","@type":"WebSite",'
            '"name":"Østfoldbussen","url":"https://ostfoldbussen.no",'
            '"inLanguage":"nb-NO"}</script>'
        )
    else:
        seo_head = '<meta name="robots" content="noindex">' 
    header = (
        '<header class="site-header"><div class="wrap header-inner">'
        f"{_brand()}{_menu()}</div></header>"
    ) if nav else ""
    contact = public.get("contact_email")
    contact_html = (f'<a href="mailto:{escape(contact)}">{escape(contact)}</a>' if contact else "")
    analytics = ""
    if public.get("matomo_enabled"):
        base = public.get("matomo_url") or "https://ostfoldbussen.no/"
        if not base.endswith("/"):
            base += "/"
        site_id = escape(str(public.get("matomo_site_id") or "1"))
        analytics = (
            f'<script src="/matomo-init.js" defer '
            f'data-matomo-url="{escape(base)}" data-matomo-site="{site_id}"></script>'
        )
    footer = (
        '<footer class="site-footer"><div class="wrap">'
        '<div class="footer-grid">'
        f'<div class="footer-brand">{_brand()}<p>Et selvstendig, privat og ikke-kommersielt '
        "initiativ for kollektivtrafikkinformasjon i Østfold – for dem som heller vil "
        "bruke vanlig SMS.</p>"
        '<p class="footer-credit">Tjenesten er utviklet av '
        '<a href="https://knutmichael.com" target="_blank" rel="noopener noreferrer">'
        'Knut Michael Haugland<span class="sr-only"> (åpnes i nytt vindu)</span></a>. '
        "Kildekoden er lisensiert under MIT-lisensen.</p></div>"
        '<div class="footer-col"><h3>Tjenesten</h3><nav aria-label="Tjenestelenker">'
        '<a href="/slik-fungerer-det">Slik fungerer det</a>'
        '<a href="/om">Om Østfoldbussen</a>'
        '<a href="/kontakt">Kontakt</a>'
        "</nav></div>"
        '<div class="footer-col"><h3>Informasjon</h3><nav aria-label="Informasjonslenker">'
        '<a href="/personvern">Personvern</a>'
        '<a href="/data">Data og lisens</a>'
        '<a href="/status">Driftsstatus</a>'
        '<a href="https://github.com/knutmichaelhaugland/ostfoldbussen" '
        'rel="noopener noreferrer">GitHub</a>'
        "</nav></div></div>"
        '<div class="footer-bottom"><span>Reisedata fra Entur (NLOD 2.0). '
        "Rutetider kan endres; operatørene er autoritative.</span>"
        f"<span>{contact_html}</span></div>"
        "</div></footer>"
    )
    return (
        '<!doctype html><html lang="no"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{escape(title)} · Østfoldbussen</title>'
        f'<meta name="description" content="{escape(description)}">'
        f"{seo_head}"
        '<link rel="icon" href="data:image/svg+xml,'
        '%3Csvg xmlns=%27http://www.w3.org/2000/svg%27 viewBox=%270 0 48 48%27%3E'
        '%3Crect width=%2748%27 height=%2748%27 rx=%2713%27 fill=%27%230f4d34%27/%3E'
        '%3Cpath d=%27M12 33c0-9.4 7.6-17 17-17h7%27 fill=%27none%27 stroke=%27%23fbf8f1%27 '
        'stroke-width=%274%27 stroke-linecap=%27round%27/%3E%3C/svg%3E">'
        f"<style>{PUBLIC_CSS}</style></head>"
        '<body><a class="skip" href="#main">Hopp til innhold</a>'
        f"{header}<main id=\"main\">{body}</main>{footer}{analytics}</body></html>"
    )


# ---------------------------------------------------------------------------
# Offentlige sider
# ---------------------------------------------------------------------------
def home(public: dict | None = None) -> str:
    public = public or {}
    number = _public_number_block(public)
    body = f"""
<section class="hero">
  <div class="wrap hero-grid">
    <div class="hero-content">
      <p class="kicker">Enklere bussinformasjon</p>
      <h1>Når går bussen?</h1>
      <p class="tagline">Bare send en SMS.</p>
      <p class="lead">Finn busstider og planlegg reisen med en helt vanlig mobiltelefon.
      Ingen app, ingen smarttelefon og ingen innlogging.</p>
      <ul class="hero-benefits">
        <li>Gratis tjeneste</li>
        <li>Ingen app</li>
        <li>Ingen innlogging</li>
      </ul>
    </div>
    <aside class="hero-action" aria-label="Send SMS til Østfoldbussen">
      {number}
    </aside>
  </div>
</section>

<section class="conversation-demo">
  <div class="wrap conversation-layout">
    <div class="conversation-intro">
      <p class="kicker">Så enkelt er det</p>
      <h2>Spør akkurat slik du pleier.</h2>
      <p>Du trenger ikke lære kommandoer eller bruke bestemte ord. Skriv spørsmålet
      ditt slik du ville spurt en venn.</p>
      <p class="conversation-note">Svaret bygger på tilgjengelige reisedata. Er noe uklart,
      spør tjenesten heller enn å gjette.</p>
    </div>
    <div class="conversation-visual">{_phone_illustration()}</div>
  </div>
</section>

<section class="band">
  <div class="wrap">
    <div class="section-head single">
      <p class="kicker">Tre enkle trinn</p>
      <h2>Slik fungerer det</h2>
    </div>
    <ol class="steps steps-three">
      <li class="step"><h3>Skriv en SMS</h3><p>Åpne meldinger på mobilen og skriv det du lurer på.</p></li>
      <li class="step"><h3>Vi sjekker</h3><p>Østfoldbussen bruker tilgjengelige reisedata for å finne et passende svar.</p></li>
      <li class="step"><h3>Få svar</h3><p>Du får bussinformasjonen tilbake på SMS.</p></li>
    </ol>
    <p class="section-note">Er noe uklart, kan Østfoldbussen spørre deg om en presisering.</p>
  </div>
</section>

<section class="band sage">
  <div class="wrap">
    <div class="benefits-head">
      <div>
        <p class="kicker">Enkelt for alle</p>
        <h2>Laget for mennesker, ikke for apper.</h2>
      </div>
      <p>Du skal ikke trenge å forstå teknologi for å finne ut når bussen går.</p>
    </div>
    <ul class="primary-benefits">
      <li class="primary-benefit"><span class="tick" aria-hidden="true">✓</span>
        <h3>Gratis å bruke</h3>
        <p>Østfoldbussen tar ikke betalt. Vanlig SMS-takst fra mobiloperatøren kan gjelde.</p>
      </li>
      <li class="primary-benefit"><span class="tick" aria-hidden="true">✓</span>
        <h3>Fungerer på vanlige mobiler</h3>
        <p>Du trenger ikke smarttelefon, internett eller apper.</p>
      </li>
      <li class="primary-benefit"><span class="tick" aria-hidden="true">✓</span>
        <h3>Spør med dine egne ord</h3>
        <p>Ingen kodeord eller kompliserte kommandoer.</p>
      </li>
    </ul>
    <div class="secondary-benefits">
      <h3>I tillegg kan du</h3>
      <ul>
        <li>finne avgangstider</li>
        <li>finne reiser fra A til B</li>
        <li>få informasjon om bussbytter</li>
        <li>stille oppfølgingsspørsmål</li>
      </ul>
    </div>
  </div>
</section>

<section class="band">
  <div class="wrap">
    <div class="section-head">
      <div><p class="kicker">Eksempler</p><h2>Hva kan du spørre om?</h2></div>
      <p>Skriv som du ville spurt en venn. Tjenesten forstår vanlige norske formuleringer.</p>
    </div>
    <div class="featured-examples">
      <p class="example-featured">Når går buss 22 fra Skredderåsen?</p>
      <p class="example-featured">Hvordan kommer jeg fra Moss til Sarpsborg?</p>
      <p class="example-featured">Jeg må være i Fredrikstad før klokken 11.</p>
    </div>
    <p class="example-more">Du kan også spørre om neste buss fra en holdeplass, om du må
    bytte buss, eller når siste buss går hjem.</p>
  </div>
</section>

<section class="band ivory">
  <div class="wrap">
    <div class="pricing">
      <div class="pricing-price">
        <p class="kicker">Hva koster det?</p>
        <p class="free">0 kr</p>
      </div>
      <div>
        <h2>Østfoldbussen er gratis.</h2>
        <p>Vi tar ikke betalt for tjenesten. Du trenger ingen konto eller abonnement hos oss.</p>
        <p>Når du sender SMS, kan mobiloperatørens vanlige SMS-takst gjelde. For mange er SMS
        inkludert i mobilabonnementet.</p>
      </div>
    </div>
  </div>
</section>

<section class="band">
  <div class="wrap why-grid">
    <div>
      <p class="kicker">Hvorfor finnes Østfoldbussen?</p>
      <h2>Kollektivtransport skal være tilgjengelig for alle.</h2>
      <p>Ikke alle har smarttelefon. Ikke alle bruker apper. Og ikke alle kan eller ønsker å
      skanne QR-koder på bussholdeplassen.</p>
      <p>Østfoldbussen er et selvstendig, privatfinansiert og ikke-kommersielt initiativ som
      skal gi et enkelt alternativ.</p>
      <p>Målet er ikke å erstatte eksisterende kollektivtjenester, men å gjøre
      reiseinformasjonen lettere tilgjengelig.</p>
      <p><a href="/om">Les mer om tjenesten →</a></p>
    </div>
    <blockquote class="pullquote">«En vanlig mobiltelefon med SMS er nok.»</blockquote>
  </div>
</section>

<section class="cta">
  <div class="wrap cta-inner">
    <div class="cta-content">
      <p class="kicker">Klar til å spørre?</p>
      <h2>Send en SMS.</h2>
      <p>Skriv spørsmålet ditt og send det til nummeret. Du trenger ingen app.</p>
      <p class="contact-tip">Lagre Østfoldbussen i kontaktlisten din. Da slipper du å huske
      nummeret neste gang du skal ta bussen.</p>
    </div>
    <div class="cta-action">{number}</div>
  </div>
</section>
"""
    return _document(
        "Når går bussen? Bare send en SMS", body, public=public,
        description=("Finn busstider og planlegg reisen i Østfold med en vanlig "
                     "mobiltelefon og SMS. Ingen app eller innlogging."),
        path="/")


def _page(title: str, kicker: str, intro: str, content: str,
          public: dict | None = None, description: str | None = None) -> str:
    body = (
        f'<section class="page-hero"><div class="wrap"><p class="kicker">{escape(kicker)}</p>'
        f"<h1>{escape(title)}</h1><p>{escape(intro)}</p></div></section>"
        f'<div class="wrap prose">{content}</div>'
    )
    path = PAGE_PATHS.get(title, "/")
    return _document(title, body, public=public,
                     description=description or intro, path=path)


def how_it_works(public: dict | None = None) -> str:
    public = public or {}
    content = f"""
<p class="lead">Du trenger bare å sende en vanlig SMS. Slik gjør du det:</p>
<ol class="steps-list">
<li><strong>Skriv en SMS.</strong> Åpne meldinger på mobilen og skriv det du lurer på, for
eksempel «Når går buss 22 fra Skredderåsen?».</li>
<li><strong>Vi sjekker.</strong> Østfoldbussen bruker tilgjengelige reisedata for å finne et
passende svar.</li>
<li><strong>Få svar.</strong> Du får bussinformasjonen tilbake på SMS.</li>
</ol>
<p>Er noe uklart, kan Østfoldbussen spørre deg om en presisering.</p>
{_public_number_block(public)}
<h2>Hva kan du spørre om?</h2>
<div class="example-grid">
<p class="example">Når går buss 22 fra Skredderåsen?</p>
<p class="example">Når går neste buss fra Moss bussterminal?</p>
<p class="example">Hvordan kommer jeg fra Moss til Sarpsborg?</p>
<p class="example">Jeg må være i Fredrikstad før klokken 11.</p>
<p class="example">Må jeg bytte buss?</p>
<p class="example">Når går siste buss hjem?</p>
</div>
<h2>Hva slags svar får du?</h2>
<p>Svaret bygger på tilgjengelige kollektivdata. Når sanntidsdata mangler, merkes svaret som
rutetider – vi later ikke som det er sanntid. Er et sted eller et tidspunkt uklart, spør
tjenesten heller enn å gjette.</p>
<p>Reiseforslaget er det første som gir en gyldig reise med nødvendig overgang. En senere
avgang kan derfor bli valgt dersom en tidligere ikke rekker forbindelsen.</p>
<p class="note">Tjenesten er laget for å være enkel å bruke med tastatur på en vanlig mobil.
Du trenger ikke spesielle kommandoer.</p>
"""
    return _page("Slik fungerer det", "Veiledning", "Slik spør du Østfoldbussen på SMS.", content, public)


def about(public: dict | None = None) -> str:
    content = """
<p class="lead">Østfoldbussen er et selvstendig, privat og ikke-kommersielt initiativ for
kollektivtrafikkinformasjon i Østfold, laget for mennesker som ikke bruker apper eller
smarttelefoner.</p>
<h2>Hva tjenesten gjør</h2>
<p>Du skriver et spørsmål på SMS. Tjenesten tolker spørsmålet, slår opp holdeplasser og
henter avganger eller reiseforslag fra Entur. Svaret formateres som en kort SMS.</p>
<p>Teknologien skal ikke dominere kommunikasjonen. Målet er et forståelig svar – ikke et
teknisk svar.</p>
<h2>Prinsipper</h2>
<ul>
<li>Vi sier tydelig fra når noe er rutetider og ikke sanntid.</li>
<li>Vi kaller ikke en reise «anbefalt» dersom den bryter kvalitetskravene våre.</li>
<li>Vi lagrer ikke telefonnummer eller meldingstekst i klartekst.</li>
<li>Vi bruker åpne data fra Entur og oppgir kilde og lisens.</li>
</ul>
<h2>Utvikler og kildekode</h2>
<p>Tjenesten er utviklet av
<a href="https://knutmichael.com" target="_blank" rel="noopener noreferrer">Knut Michael
Haugland<span class="sr-only"> (åpnes i nytt vindu)</span></a>. Kildekoden er lisensiert
under MIT-lisensen og kan brukes, endres og videreutvikles fritt.</p>
<p>Reisedataene er under NLOD 2.0; se <a href="/data">Data og lisens</a>.</p>
<h2>Forbehold</h2>
<p>Rutetider kan endres. Informasjon fra transportoperatørene er autoritativ. Tjenesten kan
be om en presisering når et sted eller et tidspunkt er uklart.</p>
"""
    return _page("Om Østfoldbussen", "Om tjenesten",
                 "Et enkelt alternativ for kollektivtrafikkinformasjon i Østfold.", content, public)


def privacy(public: dict | None = None) -> str:
    public = public or {}
    email = (public.get("contact_email") or "").strip()
    contact = (f'<a href="mailto:{escape(email)}">{escape(email)}</a>'
               if email else '<a href="/kontakt">kontaktskjemaet</a>')
    content = """
<p class="note"><strong>Offisiell tjeneste.</strong> Denne teksten beskriver den
offisielle Østfoldbussen-tjenesten. En selvhostet installasjon må erstatte den med
egen behandlingsansvarlig, leverandøroversikt og kontaktinformasjon.</p>
<p class="lead">Østfoldbussen krever ingen konto. Når du sender SMS til tjenesten, behandles
opplysningene slik:</p>
<h2>Hva som behandles</h2>
<ul>
<li>Telefonnummeret ditt brukes til å sende svaret. I applikasjonens database lagres
en <strong>pseudonymisert</strong> versjon (HMAC med hemmelig nøkkel), ikke nummeret i
klartekst. Pseudonymisering er ikke det samme som anonymisering.</li>
<li>Meldingsteksten brukes til å forstå spørsmålet og gi reiseinformasjon. Den
opprinnelige SMS-teksten lagres ikke i driftsstatistikken. Dersom
meldingsfingeravtrykk er aktivert, lagres en HMAC-SHA256 beregnet med en separat
hemmelig nøkkel. Uten denne nøkkelen lagres ikke noe meldingsfingeravtrykk.</li>
<li>Dette gjelder driftsstatistikken. Kortvarig samtalekontekst kan inneholde
meldingstekst i inntil 30 minutter, og SMS-leverandøren må behandle meldingen for
å levere den.</li>
<li>Teknisk driftsdata (tidspunkt, resultattype, responstid, feilkategori) lagres for
feilsøking og kvalitet.</li>
<li>SMS-leverandøren behandler telefonnummer og meldingstekst for å kunne levere SMS-en.</li>
</ul>
<h2>Hvordan språkmodellen brukes</h2>
<p>For å forstå frie formuleringer kan meldingsteksten sendes til en språkmodell
(Qwen 235B) via Bineric AS. Modellen brukes bare til å tolke hva du spør om; reisedata
hentes fra Entur etterpå.</p>
<p>I den offisielle konfigurasjonen sendes ikke telefonnummer, navn, konto- eller
kontaktopplysninger til språkmodellen. Det er meldingsteksten og eventuell kort
samtalekontekst som sendes. Ulike adaptere og operatørkonfigurasjoner kan ha
andre dataflyter; en selvhostet installasjon må kontrollere og dokumentere sine
egne kallveier. Unngå å skrive personopplysninger du ikke vil dele.</p>
<p>Bineric AS oppgir at API-innhold ikke brukes til å trene eller evaluere modeller, og at
det bare behandles for å levere tjenesten. Bineric bruker AWS Stockholm som underdatabehandler;
både Qwen 235B og Borealis er merket som EU-hostet. Dette er leverandørens
dokumentasjon for den offisielle tjenesten; andre operatører må gjøre egne
vurderinger. Se
<a href="https://bineric.com/legal/dpa" rel="noopener noreferrer">Bineric sin databehandleravtale</a>
og <a href="https://bineric.com/legal/privacy-policy" rel="noopener noreferrer">personvernerklæring</a>.</p>
<h2>Underleverandører</h2>
<p>Vi bruker følgende leverandører for å drifte tjenesten. Alle er etablert i EØS.</p>
<div class="table-wrap">
<table class="subprocessors">
<caption>Leverandører og formål</caption>
<thead><tr><th>Leverandør</th><th>Land</th><th>Formål</th><th>Opplysninger</th></tr></thead>
<tbody>
<tr>
<td data-label="Leverandør"><strong>WAYSCloud AS</strong><br><span class="small">Org.nr. NO 833 735 462 MVA</span><br>
<a href="https://wayscloud.eu/" rel="noopener noreferrer">wayscloud.eu</a><br>
<a href="https://wayscloud.eu/legal/privacy/" rel="noopener noreferrer">personvern</a></td>
<td data-label="Land">Norge / EØS</td>
<td data-label="Formål">Server, database, kryptert backup og teknisk drift av nettsiden og SMS-tjenesten.</td>
<td data-label="Opplysninger">Teknisk driftsdata som IP-adresse og logger, samt applikasjons- og databasedata.</td>
</tr>
<tr>
<td data-label="Leverandør"><strong>inMobile ApS</strong><br><span class="small">CVR 31426472</span><br>
<a href="https://www.inmobile.com/en/privacy-policy" rel="noopener noreferrer">inMobile</a></td>
<td data-label="Land">Danmark / EØS</td>
<td data-label="Formål">SMS-gateway: mottar SMS fra deg og sender svaret tilbake.</td>
<td data-label="Opplysninger">Telefonnummer, meldingstekst og leveringsstatus. inMobile bruker teleoperatører for
selve leveringen.</td>
</tr>
<tr>
<td data-label="Leverandør"><strong>Bineric AS</strong><br><span class="small">Org.nr. 926 115 626,
Pilestredet 52, Oslo</span><br>
<a href="https://bineric.com/" rel="noopener noreferrer">bineric.com</a><br>
<a href="https://bineric.com/legal/privacy-policy" rel="noopener noreferrer">personvern</a></td>
<td data-label="Land">Norge / EU (AWS Stockholm)</td>
<td data-label="Formål">Generative APIs (Qwen 235B) for å tolke meldingens tekst.</td>
<td data-label="Opplysninger">Meldingstekst og kort samtalekontekst — <strong>ikke telefonnummer, navn eller
kontoopplysninger</strong>.</td>
</tr>
<tr>
<td data-label="Leverandør"><strong>Entur AS</strong><br>
<a href="https://developer.entur.no/" rel="noopener noreferrer">Entur</a></td>
<td data-label="Land">Norge / EØS</td>
<td data-label="Formål">Reise- og sanntidsdata (Journey Planner og Geocoder).</td>
<td data-label="Opplysninger">Holdeplass, reisetidspunkt og reisespørsmål. Telefonnummer sendes ikke.</td>
</tr>
</tbody>
</table>
</div>
<p>inMobile kan bruke teleoperatører for å levere meldingen. Deres behandling er nødvendig
for at SMS-en skal nå frem. Eventuelle underleverandører utenfor EØS må ha et gyldig
overføringsgrunnlag etter GDPR.</p>
<p>Østfoldbussen er et selvstendig initiativ. WAYSCloud er teknisk leverandør, ikke operatør
av tjenesten.</p>
<h2>Lagring og sletting</h2>
<p>Samtalekontekst brukes ikke etter 30 minutter. Utløpte rader fjernes når de
oppdages ved oppslag, eller når operatørens purge-jobb kjører. Standard
Docker-oppsett leverer ikke en automatisk timer for dette; operatøren må aktivere
og overvåke jobben. Driftsdata for forespørsler og leveranser er konfigurert til
30 dager, og avsluttede feilgjennomgangsposter til 90 dager i standardoppsettet.
Åpne feilposter beholdes til de er vurdert.</p>
<h2>Dine rettigheter</h2>
<p>Du kan be om innsyn, retting, sletting, begrensning av behandlingen og protestere mot
behandlingen. Du kan også klage til Datatilsynet. Bruk kontaktskjemaet eller e-post til
__CONTACT__ for å komme i kontakt med oss.</p>
<h2>Statistikk</h2>
<p>Dersom Matomo er aktivert, brukes et selvhostet Matomo-verktøy for å se hvor
mange som besøker nettsiden og hvilke sider som brukes. Sporingen er uten informasjonskapsler (cookies), bruker ikke tredjeparter, og sporer ikke deg på
tvers av nettsteder. Vi lagrer ikke meldingstekst eller telefonnummer fra SMS i
statistikken. Matomo er av i standardoppsettet og må konfigureres av operatøren.</p>
<h2>Behandlingsansvarlig</h2>
<p>Østfoldbussen er et privat, ikke-kommersielt initiativ. Behandlingsansvarlig er
Knut Michael Haugland. Kontakt oss via __CONTACT__ eller
<a href="/kontakt">kontaktskjemaet</a>.</p>
<p class="note">Sist oppdatert: 7. november 2026.</p>
"""
    content = content.replace("__CONTACT__", contact)
    return _page("Personvern", "Personvern",
                 "Hvordan opplysninger behandles når du bruker Østfoldbussen.", content, public)


def data_page(public: dict | None = None) -> str:
    content = """
<p class="lead">Reise- og sanntidsdata hentes fra <a href="https://developer.entur.no/">Entur</a>
sine åpne tjenester: Journey Planner v3 og Geocoder v3.</p>
<h2>Lisens</h2>
<p>Dataene er tilgjengelig under <strong>Norsk lisens for offentlige data (NLOD) 2.0</strong>.
Ved gjenbruk skal kilden oppgis, og endringer skal merkes. Se
<a href="https://data.norge.no/nlod/no/2.0">NLOD 2.0</a>.</p>
<h2>Attribusjon</h2>
<p><strong>Kilde:</strong> Entur – reise- og sanntidsdata for kollektivtrafikk (NLOD 2.0),
hentet via Journey Planner v3 og Geocoder v3. I SMS-svar brukes kortformen «Kilde: Entur»
der det er plass.</p>
<h2>Forbehold</h2>
<p>Sanntidsdata kan mangle eller være forsinket. Når sanntidsflagg mangler, merker
tjenesten svaret som rutetider. Endringer i Enturs API-er kan påvirke tjenesten.</p>
<h2>Kildekode</h2>
<p>Prosjektets kildekode og tekniske dokumentasjon ligger på
<a href="https://github.com/knutmichaelhaugland/ostfoldbussen" rel="noopener noreferrer">GitHub</a>.
Koden er lisensiert under <strong>MIT-lisensen</strong>: den kan brukes, kopieres, endres,
deles og videreutvikles fritt, også kommersielt, så lenge opphavsretts- og lisensnotisen
beholdes.</p>
<p>Repoet er foreløpig privat. Det gjennomføres en opprydning i repoet før det åpnes i uke 46.
Lisensfilen ligger i prosjektet og gjelder når koden gjøres tilgjengelig. Reisedataene fra
Entur er under NLOD 2.0 og er ikke omfattet av MIT-lisensen.</p>
"""
    return _page("Data og lisens", "Åpne data",
                 "Kilde, lisens og forbehold for kollektivdataene.", content, public)


def contact(public: dict | None = None, *, error: str | None = None,
            sent: bool = False, values: dict | None = None) -> str:
    public = public or {}
    values = values or {}
    email = (public.get("contact_email") or "").strip()
    email_block = (
        f'<p class="contact-email">Du kan også sende e-post til '
        f'<a href="mailto:{escape(email)}">{escape(email)}</a>.</p>'
        if email else ""
    )
    ready = bool(public.get("contact_form_ready"))
    name = escape(values.get("name", ""))
    address = escape(values.get("email", ""))
    disabled = "" if ready else " disabled"
    note = ""
    if not ready:
        note = (
            '<p class="note">Kontaktskjemaet er ikke aktivert ennå. '
            + (f'Send e-post direkte til <a href="mailto:{escape(email)}">{escape(email)}</a>.'
               if email else "Kontaktinformasjon er ikke tilgjengelig ennå.")
            + "</p>"
        )
    status = ""
    if sent:
        status = ('<p class="form-status ok" role="status">Takk for meldingen. '
                  "Vi svarer på e-postadressen du oppgav.</p>")
    elif error:
        status = f'<p class="form-status error" role="alert">{escape(error)}</p>'
    content = f"""
<p class="lead">Har du spørsmål om Østfoldbussen, personvern eller tilgjengelighet?
Send oss en melding eller e-post.</p>
{email_block}
<h2>Send en melding</h2>
{note}
{status}
<form class="contact-form" method="post" action="/kontakt">
  <div class="hp" aria-hidden="true">
    <label for="contact-website">Ikke fyll ut dette feltet</label>
    <input id="contact-website" name="website" type="text" tabindex="-1" autocomplete="off">
  </div>
  <div class="form-field">
    <label for="contact-name">Navn <span class="optional">(valgfritt)</span></label>
    <input id="contact-name" name="name" type="text" maxlength="100"
           autocomplete="name" value="{name}">
  </div>
  <div class="form-field">
    <label for="contact-email">E-postadresse</label>
    <input id="contact-email" name="email" type="email" maxlength="200" required
           autocomplete="email" value="{address}">
  </div>
  <div class="form-field">
    <label for="contact-message">Melding</label>
    <textarea id="contact-message" name="message" rows="6" maxlength="4000"
              required></textarea>
  </div>
  <label class="form-consent">
    <input type="checkbox" name="consent" value="1" required>
    <span>Jeg har lest <a href="/personvern">personvernserklæringen</a> og forstår
    hvordan opplysningene behandles.</span>
  </label>
  <button class="sms-button contact-submit" type="submit"{disabled}>Send melding</button>
</form>
"""
    return _page("Kontakt", "Kontakt", "Kontaktinformasjon for Østfoldbussen.", content, public)


_MONTHS = ("januar", "februar", "mars", "april", "mai", "juni", "juli",
           "august", "september", "oktober", "november", "desember")

_STATE_TEXT = {
    "OK": ("Fungerer", "ok"),
    "DEGRADED": ("Har problemer", "bad"),
    "NOT CONFIGURED": ("Ikke i bruk", "warn"),
    "DISABLED": ("Ikke i bruk", "warn"),
    "PENDING PROVISIONING": ("Ikke aktivert ennå", "warn"),
    "UNKNOWN": ("Vet ikke", "warn"),
}


def _human_checked(value: str) -> str:
    try:
        moment = datetime.fromisoformat(str(value)).astimezone(ZoneInfo("Europe/Oslo"))
    except (ValueError, TypeError):
        return ""
    return f"{moment.day}. {_MONTHS[moment.month - 1]} {moment.year} kl. {moment:%H:%M}"


def status_page(snapshot: dict, public: dict | None = None) -> str:
    public = public or {}
    components = snapshot.get("components", {})
    labels = (("entur", "Reiseinformasjon"), ("db", "Tjenesten"), ("sms", "SMS"))
    notice = (public.get("status_notice") or "").strip()
    rows = []
    problems = False
    for key, label in labels:
        state = str(components.get(key, {}).get("state", "UNKNOWN"))
        text, css = _STATE_TEXT.get(state, ("Vet ikke", "warn"))
        if notice and key == "sms":
            text, css = "Utfordringer", "warn"
        if key in {"entur", "db"} and state != "OK":
            problems = True
        if notice and key == "sms":
            problems = True
        rows.append(f'<li><span>{escape(label)}</span>'
                    f'<strong class="{css}">{escape(text)}</strong></li>')
    if problems:
        overall = "Noen deler har problemer akkurat nå. Prøv igjen senere."
    elif str(components.get("sms", {}).get("state")) == "OK":
        overall = "Alt fungerer som det skal."
    else:
        overall = "Tjenesten fungerer som normalt. SMS er ikke aktivert ennå."
    checked = _human_checked(snapshot.get("checked_at", ""))
    updated = (f'<p class="number-note">Sist oppdatert: {escape(checked)}.</p>'
               if checked else "")
    notice_html = (f'<p class="status-notice" role="status">{escape(notice)}</p>'
                   if notice else "")
    content = f"""
{notice_html}
<p class="lead">{escape(overall)}</p>
<ul class="status-list">{''.join(rows)}</ul>
{updated}
<p class="number-note">Er noe galt, prøv igjen om litt. Reiseinformasjonen kommer fra Entur.</p>
"""
    return _page("Driftsstatus", "Drift", "Enkel status for Østfoldbussen.", content, public)


def _admin_document(title: str, body: str, *, admin_user: str = "",
                    csrf_token: str = "") -> str:
    logout = (
        '<form method="post" action="/admin/logout" class="logout-form">'
        f'<input type="hidden" name="csrf" value="{escape(csrf_token)}">'
        '<button type="submit" class="logout-button">Logg ut</button></form>'
        if csrf_token else ""
    )
    nav = (
        '<nav class="wrap"><strong>Østfoldbussen admin</strong> '
        '<a href="/admin/health">Helse</a>'
        '<a href="/admin/requests">Forespørsler</a>'
        '<a href="/admin/errors">Feil</a>'
        '<a href="/admin/deliveries">Leveranser</a>'
        '<a href="/admin/costs">Kostnader</a>'
        '<a href="/">Offentlig side</a>'
        f'{logout}'
        f'<span class="muted">{escape(admin_user)}</span>'
        "</nav>"
    )
    return (
        "<!doctype html><html lang=\"no\"><head><meta charset=\"utf-8\">"
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="robots" content="noindex,nofollow">'
        f"<title>{escape(title)} · Admin · Østfoldbussen</title><style>{BASE_CSS}</style></head>"
        '<body><a class="skip" href="#main">Hopp til innhold</a>'
        f"<header>{nav}</header><main id=\"main\">{body}</main></body></html>"
    )


# ---------------------------------------------------------------------------
def sitemap_xml() -> str:
    pages = ["/", "/slik-fungerer-det", "/om", "/kontakt", "/personvern",
             "/data", "/status"]
    urls = "".join(f"<url><loc>{escape(SITE_URL + path)}</loc></url>" for path in pages)
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f"{urls}</urlset>")


def robots_txt() -> str:
    return ("User-agent: *\n"
            "Allow: /\n"
            "Disallow: /admin\n"
            "Disallow: /api/\n"
            "Disallow: /matomo.php\n"
            "Disallow: /matomo.js\n"
            f"Sitemap: {SITE_URL}/sitemap.xml\n")


def error_page(status_code: int, title: str, message: str) -> str:
    body = (
        f"<h1>{escape(title)}</h1><p>{escape(message)}</p>"
        '<p><a href="/">Tilbake til forsiden</a></p>'
    )
    return _document(f"Feil {status_code}", body, nav=False, seo=False)


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------
def admin_login(*, csrf_token: str, error: str = "") -> str:
    error_html = f'<p class="badge bad">{escape(error)}</p>' if error else ""
    body = f"""
<h1>Admin – logg inn</h1>
<p class="muted">Administrasjon. Kun autoriserte operatører.</p>
{error_html}
<form method="post" action="/admin/login">
  <input type="hidden" name="csrf" value="{escape(csrf_token)}">
  <p><label>Bruker<br><input type="text" name="username" autocomplete="username" required></label></p>
  <p><label>Passord<br><input type="password" name="password" autocomplete="current-password" required></label></p>
  <p><button type="submit">Logg inn</button></p>
</form>
"""
    return _document("Logg inn", body)


def admin_health(snapshot: dict, *, counts: dict, obs: dict | None = None,
                 csrf_token: str = "") -> str:
    components = snapshot.get("components", {})
    rows = "".join(
        f"<tr><td>{escape(key)}</td><td>{escape(str(components.get(key, {}).get('state', 'UKJENT')))}</td>"
        f"<td>{escape(str(components.get(key, {}).get('last_success') or '-'))}</td></tr>"
        for key in ("entur", "db", "llm", "sms")
    )
    body = f"""
<h1>Helse</h1>
<div class="card">
<p>Samlet: <strong>{escape(str(snapshot.get('status')))}</strong> ·
Bygg: <code>{escape(str(snapshot.get('build_sha')))}</code> ·
Oppetid: {escape(str(snapshot.get('uptime_s')))} s</p>
</div>
<table><thead><tr><th>Komponent</th><th>Tilstand</th><th>Sist OK</th></tr></thead>
<tbody>{rows}</tbody></table>
<h2>Forespørsler</h2>
<pre>{escape(str(counts))}</pre>
<h2>Observabilitet (OBS-01…OBS-14)</h2>
{_obs_table(obs or {})}
"""
    return _admin_document("Helse", body, csrf_token=csrf_token)


def _obs_table(obs: dict) -> str:
    signals = obs.get("signals") or []
    if not signals:
        return '<p class="muted">Ingen observabilitetsdata.</p>'
    rows = []
    for signal in signals:
        state = str(signal.get("state", "UNKNOWN"))
        css = "ok" if state == "HEALTHY" else ("bad" if state in {"DEGRADED", "UNAVAILABLE"} else "warn")
        rows.append(
            f"<tr><td>{escape(str(signal.get('id', '')))}</td>"
            f"<td>{escape(str(signal.get('name', '')))}</td>"
            f"<td><span class=\"badge {css}\">{escape(state)}</span></td>"
            f"<td>{escape(str(signal.get('detail', '')))}</td></tr>"
        )
    return (
        "<table><thead><tr><th>ID</th><th>Signal</th><th>Tilstand</th><th>Detalj</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
        f"<p class=\"muted\">Sjekket: {escape(str(obs.get('checked_at', '')))}</p>"
    )


def admin_table(title: str, columns: list[str], rows: list[dict], *, empty: str = "Ingen rader.",
                csrf_token: str = "") -> str:
    head = "".join(f"<th>{escape(column)}</th>" for column in columns)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{escape(str(row.get(column, '')))}</td>" for column in columns)
        body_rows.append(f"<tr>{cells}</tr>")
    table = (
        f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"
        if body_rows
        else f'<p class="muted">{escape(empty)}</p>'
    )
    return _admin_document(title, f"<h1>{escape(title)}</h1>{table}", csrf_token=csrf_token)


def admin_costs(counters: dict, *, day: str, sms_rate: str, llm_rate: str,
                csrf_token: str = "") -> str:
    rows = [
        {"Teller": key, "Verdi": value}
        for key, value in sorted(counters.items())
    ]
    table = admin_table_body(["Teller", "Verdi"], rows)
    body = f"""
<h1>Kostnader og forbruk – {escape(day)}</h1>
{table}
<h2>Kostnadsestimat</h2>
<p>SMS-enhetskostnad: <strong>{escape(sms_rate)}</strong> ·
LLM-enhetskostnad: <strong>{escape(llm_rate)}</strong></p>
<p class="muted">Tallene over er tellere, ikke faktura. Priser er ikke vedtatt og vises som
UKJENT dersom de ikke er konfigurert. Ingen betalte tjenester er aktive uten konfigurasjon.</p>
"""
    return _admin_document("Kostnader", body, csrf_token=csrf_token)


def admin_table_body(columns: list[str], rows: list[dict]) -> str:
    head = "".join(f"<th>{escape(column)}</th>" for column in columns)
    body_rows = "".join(
        "<tr>" + "".join(f"<td>{escape(str(row.get(column, '')))}</td>" for column in columns) + "</tr>"
        for row in rows
    )
    if not body_rows:
        return '<p class="muted">Ingen rader.</p>'
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body_rows}</tbody></table>"


def admin_requests(rows: list[dict], *, csrf_token: str = "") -> str:
    columns = ["id", "created_at", "sender_pseudonym", "intent", "result_type", "status",
               "latency_ms", "error_category", "channel"]
    body = f"""
<h1>Forespørsler</h1>
<p class="muted">Sender vises som kort pseudonym. Rå telefonnummer og meldingstekst lagres ikke.</p>
{admin_table_body(columns, rows)}
"""
    return _admin_document("Forespørsler", body, csrf_token=csrf_token)


def admin_errors(rows: list[dict], *, csrf_token: str = "") -> str:
    columns = ["id", "created_at", "sender_pseudonym", "intent", "result_type", "status",
               "latency_ms", "error_category", "channel"]
    body = f"""
<h1>Feil</h1>
<p class="muted">Kun tekniske feil og feilkategorier. Ingen meldingstekst.</p>
{admin_table_body(columns, rows)}
"""
    return _admin_document("Feil", body, csrf_token=csrf_token)


def admin_error_reviews(rows: list[dict], *, counts: dict, csrf_token: str) -> str:
    """Feilgjennomgangskø (mandat §10) med feltene mandatet krever."""
    display = []
    for row in rows:
        item = dict(row)
        item["place_ids"] = ", ".join(item.get("place_ids") or [])
        display.append(item)
    columns = [
        "id", "created_at", "category", "failure_stage", "pseudonym_ref",
        "place_ids", "build_sha", "suggested_correction", "regression_ref",
        "review_status",
    ]
    summary = " · ".join(
        f"{escape(str(key))}: {escape(str(value))}" for key, value in sorted(counts.items())
    )
    status_options = "".join(
        f'<option value="{value}">{value}</option>' for value in ("OPEN", "REVIEWED", "FIXED")
    )
    body = f"""
<h1>Feilgjennomgang</h1>
<p class="muted">Kø for feilede eller uklare forespørsler. Ingen meldingstekst, ingen
rå telefonnummer. Pseudonym er kort referanse.</p>
<p>{summary or "Ingen poster."}</p>
{admin_table_body(columns, display)}
<h2>Oppdater post</h2>
<form method="post" action="/admin/errors" class="admin-form">
  <input type="hidden" name="csrf" value="{escape(csrf_token)}">
  <label>ID <input type="number" name="id" min="1" required></label>
  <label>Status <select name="status">{status_options}</select></label>
  <label>Notat <input type="text" name="note" maxlength="500"></label>
  <button type="submit">Lagre</button>
</form>
"""
    return _admin_document("Feilgjennomgang", body, csrf_token=csrf_token)


def admin_deliveries(rows: list[dict], *, csrf_token: str = "") -> str:
    columns = ["id", "provider_message_id", "request_id", "status", "created_at", "updated_at"]
    body = f"""
<h1>Leveranser</h1>
<p class="muted">SMS-leveranser (inn/ut). Ingen telefonnummer vises.</p>
{admin_table_body(columns, rows)}
"""
    return _admin_document("Leveranser", body, csrf_token=csrf_token)


def admin_table_page(title: str, columns: list[str], rows: list[dict], intro: str = "",
                     csrf_token: str = "") -> str:
    intro_html = f'<p class="muted">{escape(intro)}</p>' if intro else ""
    body = f"<h1>{escape(title)}</h1>{intro_html}{admin_table_body(columns, rows)}"
    return _admin_document(title, body, csrf_token=csrf_token)
