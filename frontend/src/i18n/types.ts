/** The zh-TW dictionaries must match the English key shape exactly; English is canonical. */
export type DictionaryShape<T> = {
  [K in keyof T]: T[K] extends string ? string : DictionaryShape<T[K]>
}
