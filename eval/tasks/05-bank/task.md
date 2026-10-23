Write the module `bank.vl`:

    pub type Account = struct {
        owner: Str
        balance: Int
    }

    pub fn open(owner: Str) -> Account
    pub fn deposit(a: mut Account, amount: Int) -> Result[Int, Str]
    pub fn withdraw(a: mut Account, amount: Int) -> Result[Int, Str]
    pub fn transfer(from: mut Account, to: mut Account, amount: Int) -> Result[Unit, Str]

- `open` makes an account with a balance of 0.
- `deposit` adds the amount and returns the new balance.
- `withdraw` takes the amount away and returns the new balance.
- `transfer` moves the amount from one account to the other.

Each fails with `Err("amount must be positive")` when the amount is 0 or
less, and `withdraw` and `transfer` with `Err("insufficient funds")` when
the balance is smaller than the amount. When a function fails it changes
nothing.
