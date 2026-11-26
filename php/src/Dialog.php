<?php
declare(strict_types=1);

namespace Qtool;

/**
 * Слияние контекста диалога: короткое уточнение наследует предыдущий запрос,
 * самостоятельное сообщение (группа или код) — нет.
 * Порт is_clarification / is_self_contained_query из src/catalog_search.py.
 */
final class Dialog
{
    /** @param array<string,true> $insertPrefixes */
    public static function isClarification(string $text, array $insertPrefixes = []): bool
    {
        $low = trim(Normalize::low($text));
        if ($low === '') {
            return true;
        }
        $known = Codes::COMMON_INSERT_PREFIXES;
        foreach ($insertPrefixes as $p => $_) {
            $known[strtoupper((string)$p)] = true;
        }
        $rest = preg_replace_callback('/' . Compat::RE_UNDER_INSERT . '/iu', static function ($m) use ($known) {
            $word = Codes::insertPrefixFromWord($m[1], $known);
            return ($word !== null && isset($known[$word])) ? ' под ' : $m[0];
        }, $low);
        $rest = preg_replace('/' . Compat::RE_UNDER_SIZE . '/iu', ' под ', $rest);
        $rest = preg_replace('/' . Compat::RE_UNDER_PLATE . '/iu', ' под ', $rest);
        if (Codes::insertCodeFromText($rest) !== null) {
            return false;
        }
        if (Codes::holderCodeFromText($rest) !== null) {
            return false;
        }
        $short = [];
        if (preg_match('/(?<![a-z0-9])([a-z]{2,5})\s?(\d{2})(?![a-z0-9])/u', $rest, $short)) {
            $pref = Codes::insertPrefixFromWord($short[1], $known);
            if ($pref !== null && isset($known[$pref]) && str_contains(Codes::ISO_CLEARANCE, $pref[1])) {
                return false;
            }
        }
        $toks = [];
        preg_match_all('/' . Compat::RE_TOKEN . '/u', $rest, $toks);
        foreach ($toks[0] as $tok) {
            if (Normalize::fullmatch(Compat::RE_NUMBER, $tok)
                || Normalize::fullmatch(Compat::RE_THREAD_SIZE, $tok)
                || Normalize::fullmatch(Compat::clarifyWordPattern(), $tok)) {
                continue;
            }
            $head = [];
            if (preg_match('/^([a-zа-яё]{2,6})(\d*)$/uD', $tok, $head)
                && $head[2] === ''
                && ($w = Codes::insertPrefixFromWord($head[1], $known)) !== null
                && isset($known[$w])) {
                continue;
            }
            return false;
        }
        return true;
    }

    public static function isSelfContainedQuery(string $text): bool
    {
        return !self::isClarification($text);
    }
}