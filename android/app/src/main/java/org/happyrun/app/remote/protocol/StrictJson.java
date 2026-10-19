package org.happyrun.app.remote.protocol;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Bounded JSON grammar; rejects duplicate keys, coercions, invalid Unicode and nonfinite numbers. */
public final class StrictJson {
    public static final int MAX_CHARS = 262144;
    private final String input;
    private int position;
    private int values;
    private StrictJson(String input) { this.input = input; }
    private static IllegalArgumentException invalid() { return new IllegalArgumentException("invalid_protocol_json"); }
    public static Object parse(String input) {
        if (input == null || input.length() > MAX_CHARS) throw invalid();
        StrictJson parser = new StrictJson(input);
        Object value = parser.value(0);
        parser.space();
        if (parser.position != input.length()) throw invalid();
        return value;
    }
    private void space() { while (position < input.length() && " \r\n\t".indexOf(input.charAt(position)) >= 0) position++; }
    private boolean take(char c) { space(); if (position < input.length() && input.charAt(position) == c) { position++; return true; } return false; }
    private Object value(int depth) {
        if (depth > 32 || ++values > 8192) throw invalid();
        space(); if (position >= input.length()) throw invalid();
        char c = input.charAt(position);
        if (c == '"') return string();
        if (c == '{') {
            position++; Map<String,Object> result = new LinkedHashMap<>();
            if (take('}')) return result;
            do {
                space(); if (position >= input.length() || input.charAt(position) != '"') throw invalid();
                String key = string(); if (!take(':') || result.containsKey(key)) throw invalid();
                result.put(key,value(depth+1));
                if (take('}')) return result;
            } while (take(','));
            throw invalid();
        }
        if (c == '[') {
            position++; List<Object> result = new ArrayList<>();
            if (take(']')) return result;
            do { result.add(value(depth+1)); if (take(']')) return result; } while (take(','));
            throw invalid();
        }
        for (String keyword : new String[]{"true","false","null"}) {
            if (input.startsWith(keyword,position)) {
                position += keyword.length();
                return keyword.equals("null") ? null : Boolean.valueOf(keyword);
            }
        }
        int start = position;
        while (position < input.length() && "-+0123456789.eE".indexOf(input.charAt(position)) >= 0) position++;
        String number = input.substring(start,position);
        if (!number.matches("-?(?:0|[1-9][0-9]*)(?:\\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")) throw invalid();
        try {
            if (number.indexOf('.') < 0 && number.indexOf('e') < 0 && number.indexOf('E') < 0) return Long.valueOf(number);
            BigDecimal decimal = new BigDecimal(number);
            if (!Double.isFinite(decimal.doubleValue())) throw invalid();
            return decimal;
        } catch (NumberFormatException failure) { throw invalid(); }
    }
    private String string() {
        position++; StringBuilder result = new StringBuilder(); boolean ended = false;
        while (position < input.length()) {
            char c = input.charAt(position++);
            if (c == '"') { ended = true; break; }
            if (c < 32) throw invalid();
            if (c == '\\') {
                if (position >= input.length()) throw invalid();
                char escape = input.charAt(position++);
                switch (escape) {
                    case '"': case '\\': case '/': c=escape; break;
                    case 'b': c='\b'; break; case 'f': c='\f'; break;
                    case 'n': c='\n'; break; case 'r': c='\r'; break; case 't': c='\t'; break;
                    case 'u':
                        if (position+4 > input.length()) throw invalid();
                        String hex = input.substring(position,position+4);
                        if (!hex.matches("[0-9a-fA-F]{4}")) throw invalid();
                        c=(char)Integer.parseInt(hex,16); position+=4; break;
                    default: throw invalid();
                }
            }
            result.append(c);
        }
        if (!ended) throw invalid();
        unicode(result.toString()); return result.toString();
    }
    private static void unicode(String value) {
        for (int i=0;i<value.length();i++) {
            char c=value.charAt(i);
            if (Character.isHighSurrogate(c)) {
                if (++i >= value.length() || !Character.isLowSurrogate(value.charAt(i))) throw invalid();
            } else if (Character.isLowSurrogate(c)) throw invalid();
        }
    }
    public static String write(Object value) {
        StringBuilder out = new StringBuilder(); append(out,value,0);
        if (out.length() > MAX_CHARS) throw invalid(); return out.toString();
    }
    private static void append(StringBuilder out,Object value,int depth) {
        if (depth > 32 || out.length() > MAX_CHARS) throw invalid();
        if (value == null) {out.append("null");return;}
        if (value instanceof String) {
            String text=(String)value; unicode(text);out.append('"');
            for (char c:text.toCharArray()) {
                if (c=='"' || c=='\\') out.append('\\').append(c);
                else if(c<32) out.append(String.format(java.util.Locale.ROOT,"\\u%04x",(int)c));
                else out.append(c);
            }
            out.append('"');return;
        }
        if (value instanceof Boolean || value instanceof Long || value instanceof Integer || value instanceof BigDecimal) {out.append(value);return;}
        if (value instanceof Map) {
            out.append('{');boolean comma=false;
            for (Map.Entry<?,?> entry:((Map<?,?>)value).entrySet()) {
                if (!(entry.getKey() instanceof String)) throw invalid();
                if(comma)out.append(',');comma=true;append(out,entry.getKey(),depth+1);out.append(':');append(out,entry.getValue(),depth+1);
            } out.append('}');return;
        }
        if (value instanceof List) {
            out.append('[');boolean comma=false;
            for(Object item:(List<?>)value) {if(comma)out.append(',');comma=true;append(out,item,depth+1);}out.append(']');return;
        }
        throw invalid();
    }
}
