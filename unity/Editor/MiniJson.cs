using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Text;

namespace TalkingAvatarKit.Editor
{
    /// <summary>
    /// Small JSON reader/writer for the sidecar and the check report (JsonUtility cannot read
    /// objects keyed by name). Objects become Dictionary&lt;string, object&gt;, arrays List&lt;object&gt;,
    /// numbers double, plus string, bool and null.
    /// </summary>
    public static class MiniJson
    {
        public static object Parse(string text)
        {
            var p = new Reader(text);
            var value = p.Value();
            p.SkipSpace();
            if (!p.End) throw new FormatException($"unexpected text at {p.Pos}");
            return value;
        }

        sealed class Reader
        {
            readonly string _s;
            public int Pos;
            public Reader(string s) { _s = s; }
            public bool End => Pos >= _s.Length;

            public void SkipSpace()
            {
                while (Pos < _s.Length && char.IsWhiteSpace(_s[Pos])) Pos++;
            }

            char Peek() { SkipSpace(); if (End) throw new FormatException("unexpected end of JSON"); return _s[Pos]; }

            void Expect(char c)
            {
                if (Peek() != c) throw new FormatException($"expected '{c}' at {Pos}");
                Pos++;
            }

            public object Value()
            {
                var c = Peek();
                switch (c)
                {
                    case '{': return Obj();
                    case '[': return Arr();
                    case '"': return Str();
                    case 't': Word("true"); return true;
                    case 'f': Word("false"); return false;
                    case 'n': Word("null"); return null;
                    default: return Num();
                }
            }

            void Word(string w)
            {
                if (string.CompareOrdinal(_s, Pos, w, 0, w.Length) != 0) throw new FormatException($"bad literal at {Pos}");
                Pos += w.Length;
            }

            Dictionary<string, object> Obj()
            {
                var d = new Dictionary<string, object>();
                Expect('{');
                if (Peek() == '}') { Pos++; return d; }
                while (true)
                {
                    SkipSpace();
                    var key = Str();
                    Expect(':');
                    d[key] = Value();
                    var c = Peek();
                    Pos++;
                    if (c == '}') return d;
                    if (c != ',') throw new FormatException($"expected ',' or '}}' at {Pos}");
                }
            }

            List<object> Arr()
            {
                var l = new List<object>();
                Expect('[');
                if (Peek() == ']') { Pos++; return l; }
                while (true)
                {
                    l.Add(Value());
                    var c = Peek();
                    Pos++;
                    if (c == ']') return l;
                    if (c != ',') throw new FormatException($"expected ',' or ']' at {Pos}");
                }
            }

            string Str()
            {
                Expect('"');
                var sb = new StringBuilder();
                while (true)
                {
                    if (End) throw new FormatException("unterminated string");
                    var c = _s[Pos++];
                    if (c == '"') return sb.ToString();
                    if (c != '\\') { sb.Append(c); continue; }
                    var e = _s[Pos++];
                    switch (e)
                    {
                        case 'n': sb.Append('\n'); break;
                        case 't': sb.Append('\t'); break;
                        case 'r': sb.Append('\r'); break;
                        case 'b': sb.Append('\b'); break;
                        case 'f': sb.Append('\f'); break;
                        case 'u':
                            sb.Append((char)Convert.ToInt32(_s.Substring(Pos, 4), 16));
                            Pos += 4;
                            break;
                        default: sb.Append(e); break;
                    }
                }
            }

            object Num()
            {
                var start = Pos;
                while (Pos < _s.Length && "+-0123456789.eE".IndexOf(_s[Pos]) >= 0) Pos++;
                if (start == Pos) throw new FormatException($"unexpected character at {Pos}");
                return double.Parse(_s.Substring(start, Pos - start), NumberStyles.Float, CultureInfo.InvariantCulture);
            }
        }

        public static string Serialize(object value, bool pretty = true)
        {
            var sb = new StringBuilder();
            Write(sb, value, pretty ? 0 : -1);
            return sb.ToString();
        }

        static void Indent(StringBuilder sb, int level)
        {
            if (level < 0) return;
            sb.Append('\n').Append(' ', level * 2);
        }

        static void Write(StringBuilder sb, object v, int level)
        {
            var next = level < 0 ? -1 : level + 1;
            switch (v)
            {
                case null: sb.Append("null"); break;
                case string s: WriteString(sb, s); break;
                case bool b: sb.Append(b ? "true" : "false"); break;
                case float f: sb.Append(float.IsNaN(f) || float.IsInfinity(f) ? "null" : f.ToString("R", CultureInfo.InvariantCulture)); break;
                case double d: sb.Append(double.IsNaN(d) || double.IsInfinity(d) ? "null" : d.ToString("R", CultureInfo.InvariantCulture)); break;
                case int or long or short or uint: sb.Append(Convert.ToString(v, CultureInfo.InvariantCulture)); break;
                case IDictionary dict:
                {
                    sb.Append('{');
                    var first = true;
                    foreach (DictionaryEntry e in dict)
                    {
                        if (!first) sb.Append(',');
                        first = false;
                        Indent(sb, next);
                        WriteString(sb, e.Key.ToString());
                        sb.Append(level < 0 ? ":" : ": ");
                        Write(sb, e.Value, next);
                    }
                    if (!first) Indent(sb, level);
                    sb.Append('}');
                    break;
                }
                case IEnumerable list:
                {
                    sb.Append('[');
                    var first = true;
                    foreach (var item in list)
                    {
                        if (!first) sb.Append(',');
                        first = false;
                        Indent(sb, next);
                        Write(sb, item, next);
                    }
                    if (!first) Indent(sb, level);
                    sb.Append(']');
                    break;
                }
                default: WriteString(sb, v.ToString()); break;
            }
        }

        static void WriteString(StringBuilder sb, string s)
        {
            sb.Append('"');
            foreach (var c in s)
            {
                switch (c)
                {
                    case '"': sb.Append("\\\""); break;
                    case '\\': sb.Append("\\\\"); break;
                    case '\n': sb.Append("\\n"); break;
                    case '\r': sb.Append("\\r"); break;
                    case '\t': sb.Append("\\t"); break;
                    default:
                        if (c < 0x20) sb.Append("\\u").Append(((int)c).ToString("x4"));
                        else sb.Append(c);
                        break;
                }
            }
            sb.Append('"');
        }
    }
}
