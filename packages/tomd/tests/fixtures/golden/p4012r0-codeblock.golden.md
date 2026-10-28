---
title: "REALLY_CONVERTIBLE_TO DEFINITION"
document: P4012R0
date: 2026-06-03
reply-to:

---

<!-- tomd:summary tables=0 trusted=0 flagged=0 likely=0 marked=0 confidence=n/a unfamiliarity=0.40 -->

###### P4012R0 A `really_convertible_to` definition

###### 11.3 modify [simd.ctor]

#### In [simd.ctore], change:

```cpp
[simd.ctor]
template<class U>
  constexpr <del>explicit(see below)</del> basic_vec(U&& value) noexcept;
```

5 Let `From` denote the type `remove_cvref_t<U>`.

6 Constraints: U satisfies <del>explicitly-convertible-to&lt;value_type&gt;.</del> <ins>convertible_to&lt;value_type&gt;, and either</ins>

• From is not an arithmetic type and does not satisfy constexpr-wrapper-like,

• From is an arithmetic type and the conversion from From to value_type is value-preserving ([simd.general]), or

• From satisfies constexpr-wrapper-like, remove_cvref_t&lt;decltype(From::value)&gt; is an arithmetic type, and From::value is representable by value_type.

7 *Effects*: Initializes each element to the value of the argument after conversion to `value_type`.

8 Remarks: The expression inside explicit evaluates to false if and only if U satisfies convertible_to&lt;value_type&gt; , and either

• From is not an arithmetic type and does not satisfy constexpr-wrapper-like,

• From is an arithmetic type and the conversion from From to value_type is value-preserving ([simd.general]), or

• From satisfies constexpr-wrapper-like, remove_cvref_t&lt;decltype(From::value)&gt; is an arithmetic type, and From::value is representable by value_type.

```cpp
template <typename To, typename From>
  consteval bool converting_limits_throws()
  {
    try {
      using L = std::numeric_limits<From>;
      [[maybe_unused]] To x = L::max();
      x = L::min();
      x = L::lowest();
    } catch (...) {
      return true;
    }
    return false;
  }
template <typename From, typename To>
  concept really_convertible_to = std::convertible_to<From, To>
                                     and not converting_limits_throws<To, From>();
```

### 11
