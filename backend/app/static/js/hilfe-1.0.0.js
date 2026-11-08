/* Hilfetexte (Klasse `hilfe`) auf zwei Zeilen kuerzen, "mehr"/"weniger" zum Aufklappen.
   Ohne dieses Skript bleibt der volle Text lesbar: gekuerzt wird nur ueber die
   Klasse `hilfe--gekuerzt`, die hier gesetzt wird. */
(function () {
    var ZEILEN = 2;
    var beobachter = typeof ResizeObserver === 'function' ? new ResizeObserver(function (eintraege) {
        eintraege.forEach(function (e) { pruefen(e.target, false); });
    }) : null;

    function zeilenhoehe(el) {
        var cs = getComputedStyle(el);
        var lh = parseFloat(cs.lineHeight);
        return isNaN(lh) ? parseFloat(cs.fontSize) * 1.3 : lh;
    }

    function knopf(el) {
        var k = el.nextElementSibling;
        return k && k.classList.contains('hilfe-mehr') ? k : null;
    }

    function pruefen(el, neu) {
        var breite = el.offsetWidth;
        if (!breite) { return; }                       // verborgen: spaeter per Beobachter
        if (!neu && el._hilfeBreite === breite) { return; }
        el._hilfeBreite = breite;
        var offen = el.dataset.hilfeOffen === '1';
        el.classList.remove('hilfe--gekuerzt');
        var lang = el.scrollHeight > zeilenhoehe(el) * ZEILEN + 2;
        var k = knopf(el);
        if (!lang) { if (k) { k.remove(); } return; }
        if (!k) {
            k = document.createElement('button');
            k.type = 'button';
            k.className = 'hilfe-mehr';
            k.addEventListener('click', function () {
                var auf = el.dataset.hilfeOffen !== '1';
                el.dataset.hilfeOffen = auf ? '1' : '0';
                el.classList.toggle('hilfe--gekuerzt', !auf);
                k.textContent = auf ? 'weniger' : 'mehr';
                k.setAttribute('aria-expanded', auf ? 'true' : 'false');
            });
            el.after(k);
        }
        if (!offen) { el.classList.add('hilfe--gekuerzt'); }
        k.textContent = offen ? 'weniger' : 'mehr';
        k.setAttribute('aria-expanded', offen ? 'true' : 'false');
    }

    function anwenden(wurzel) {
        (wurzel || document).querySelectorAll('.hilfe:not([data-hilfe-voll])').forEach(function (el) {
            if (el._hilfeBeobachtet) { return; }
            el._hilfeBeobachtet = true;
            pruefen(el, true);
            if (beobachter) { beobachter.observe(el); }
        });
    }

    function start() { anwenden(document); }
    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', start); }
    else { start(); }
    window.addEventListener('load', function () {
        document.querySelectorAll('.hilfe:not([data-hilfe-voll])').forEach(function (el) { pruefen(el, true); });
    });
    document.addEventListener('htmx:afterSwap', function (e) { anwenden(e.target); });
    window.abgehaktHilfeAnwenden = anwenden;
})();
