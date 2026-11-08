// Ordered JSON values.
//
// Python dicts preserve insertion order and json.dumps emits keys in
// that order. Go maps do not. The Go core must emit the same key order
// as the Python generator so outputs can be compared byte-for-byte
// (and so a config diff is a real diff, not a reordering). Obj is an
// object that remembers its key order; JVal is a JSON value whose
// objects are *Obj, arrays are []JVal, scalars are string/float64/
// bool/nil. MarshalJSON writes keys in insertion order; UnmarshalJSON
// reads them in document order.
package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"strconv"
)

// JVal is a JSON value with order-preserving objects.
type JVal any

// Obj is a JSON object with insertion-ordered keys.
type Obj struct {
	Keys []string
	M    map[string]JVal
}

// O builds an Obj from key/value pairs in order.
func O(pairs ...any) *Obj {
	o := &Obj{M: make(map[string]JVal, len(pairs)/2)}
	for i := 0; i+1 < len(pairs); i += 2 {
		k, _ := pairs[i].(string)
		o.Set(k, pairs[i+1])
	}
	return o
}

// Set assigns a key, keeping its original position if already present.
func (o *Obj) Set(k string, v JVal) {
	if _, ok := o.M[k]; !ok {
		o.Keys = append(o.Keys, k)
	}
	o.M[k] = v
}

// Get returns the value for k, or nil when absent.
func (o *Obj) Get(k string) JVal {
	if o == nil {
		return nil
	}
	return o.M[k]
}

// MarshalJSON writes the object with keys in insertion order.
func (o *Obj) MarshalJSON() ([]byte, error) {
	var buf bytes.Buffer
	buf.WriteByte('{')
	for i, k := range o.Keys {
		if i > 0 {
			buf.WriteByte(',')
		}
		kb, err := marshalString(k)
		if err != nil {
			return nil, err
		}
		buf.Write(kb)
		buf.WriteByte(':')
		vb, err := marshalJVal(o.M[k])
		if err != nil {
			return nil, err
		}
		buf.Write(vb)
	}
	buf.WriteByte('}')
	return buf.Bytes(), nil
}

// marshalString encodes a string without HTML escaping, matching
// Python json.dumps (which never escapes <, > or &).
func marshalString(s string) ([]byte, error) {
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(s); err != nil {
		return nil, err
	}
	return bytes.TrimRight(buf.Bytes(), "\n"), nil
}

// UnmarshalJSON decodes an object preserving document key order.
func (o *Obj) UnmarshalJSON(data []byte) error {
	dec := json.NewDecoder(bytes.NewReader(data))
	t, err := dec.Token()
	if err != nil {
		return err
	}
	d, ok := t.(json.Delim)
	if !ok || d != '{' {
		return fmt.Errorf("expected object")
	}
	o.Keys = nil
	o.M = make(map[string]JVal)
	for dec.More() {
		kt, err := dec.Token()
		if err != nil {
			return err
		}
		k, _ := kt.(string)
		var raw json.RawMessage
		if err := dec.Decode(&raw); err != nil {
			return err
		}
		v, err := parseJVal(raw)
		if err != nil {
			return err
		}
		o.Set(k, v)
	}
	_, err = dec.Token() // closing '}'
	return err
}

func parseJVal(raw json.RawMessage) (JVal, error) {
	raw = bytes.TrimSpace(raw)
	if len(raw) == 0 {
		return nil, nil
	}
	switch raw[0] {
	case '{':
		o := &Obj{}
		if err := o.UnmarshalJSON(raw); err != nil {
			return nil, err
		}
		return o, nil
	case '[':
		var raws []json.RawMessage
		if err := json.Unmarshal(raw, &raws); err != nil {
			return nil, err
		}
		arr := make([]JVal, 0, len(raws))
		for _, r := range raws {
			v, err := parseJVal(r)
			if err != nil {
				return nil, err
			}
			arr = append(arr, v)
		}
		return arr, nil
	case '"':
		var s string
		if err := json.Unmarshal(raw, &s); err != nil {
			return nil, err
		}
		return s, nil
	case 't', 'f':
		var b bool
		if err := json.Unmarshal(raw, &b); err != nil {
			return nil, err
		}
		return b, nil
	case 'n':
		return nil, nil
	default:
		f, err := strconv.ParseFloat(string(raw), 64)
		if err != nil {
			return nil, err
		}
		return f, nil
	}
}

func marshalJVal(v JVal) ([]byte, error) {
	switch t := v.(type) {
	case *Obj:
		return t.MarshalJSON()
	case []JVal:
		var buf bytes.Buffer
		buf.WriteByte('[')
		for i, e := range t {
			if i > 0 {
				buf.WriteByte(',')
			}
			b, err := marshalJVal(e)
			if err != nil {
				return nil, err
			}
			buf.Write(b)
		}
		buf.WriteByte(']')
		return buf.Bytes(), nil
	default:
		// string / float64 / bool / nil: encoding/json with HTML
		// escaping disabled (Python json.dumps does not escape <>&).
		var buf bytes.Buffer
		enc := json.NewEncoder(&buf)
		enc.SetEscapeHTML(false)
		if err := enc.Encode(v); err != nil {
			return nil, err
		}
		return bytes.TrimRight(buf.Bytes(), "\n"), nil
	}
}

// Str returns the string value of a JVal, or "" when absent/not a string.
func Str(v JVal) string {
	s, _ := v.(string)
	return s
}

// Num returns the float64 value of a JVal, or 0 when absent/not a number.
func Num(v JVal) float64 {
	f, _ := v.(float64)
	return f
}

// Bool returns the bool value of a JVal, or false when absent/not a bool.
func Bool(v JVal) bool {
	b, _ := v.(bool)
	return b
}

// Arr returns the array value of a JVal, or nil when absent/not an array.
func Arr(v JVal) []JVal {
	a, _ := v.([]JVal)
	return a
}

// ObjVal returns the object value of a JVal, or nil when absent/not an object.
func ObjVal(v JVal) *Obj {
	o, _ := v.(*Obj)
	return o
}

// Truthy mirrors Python truthiness for JSON values: nil is false,
// empty string/list/object is false, 0 is false.
func Truthy(v JVal) bool {
	switch t := v.(type) {
	case nil:
		return false
	case bool:
		return t
	case string:
		return t != ""
	case float64:
		return t != 0
	case []JVal:
		return len(t) > 0
	case *Obj:
		return len(t.Keys) > 0
	default:
		return false
	}
}

// GetOr returns the value for key when the key is present (even when
// null), or def when absent. Mirrors Python dict.get(key, default).
func GetOr(o *Obj, key string, def JVal) JVal {
	if o == nil {
		return def
	}
	if v, ok := o.M[key]; ok {
		return v
	}
	return def
}
